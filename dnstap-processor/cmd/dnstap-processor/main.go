package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	powerdns_protobuf "github.com/dmachard/go-powerdns-protobuf"
	"github.com/dnstap/golang-dnstap"
	"github.com/miekg/dns"
	"google.golang.org/protobuf/proto"

	"github.com/powerblockade/dnstap-processor/internal/buffer"
	"github.com/powerblockade/dnstap-processor/internal/config"
)

var (
	Version = "0.1.0-dev"
	GitSHA  = "unknown"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	if cfg.Primary.APIKey == "" {
		log.Fatalf("PRIMARY_API_KEY is required")
	}

	log.Printf(
		"starting dnstap-processor version=%s sha=%s node=%s dnstap_socket=%s protobuf_listen=%s primary=%s buffer=%s",
		Version, GitSHA, cfg.NodeName, cfg.DnstapSocket, cfg.ProtobufListen, cfg.Primary.URL, cfg.Buffer.Path,
	)

	buf, err := buffer.Open(cfg.Buffer.Path, cfg.Buffer.MaxBytes, cfg.Buffer.MaxAge)
	if err != nil {
		log.Fatalf("buffer open: %v", err)
	}
	defer buf.Close()

	if pending := buf.Count(); pending > 0 {
		log.Printf("buffer: %d pending events from previous run", pending)
	}

	input, err := dnstap.NewFrameStreamSockInputFromPath(cfg.DnstapSocket)
	if err != nil {
		log.Fatalf("dnstap input: %v", err)
	}
	input.SetTimeout(5 * time.Second)
	input.SetLogger(log.Default())

	// Ensure the socket is connectable by the recursor process.
	// Recursor may not run as root; allow group/other write on the socket.
	_ = os.Chmod(cfg.DnstapSocket, 0o666)

	dataChan := make(chan []byte, 2048)
	go func() {
		// ReadInto blocks; it closes channel on exit.
		input.ReadInto(dataChan)
	}()

	client := &http.Client{Timeout: 5 * time.Second}

	// Load RPZ sets for blocked detection (best-effort).
	blockedSet := map[string]struct{}{}
	allowSet := map[string]struct{}{}
	lastLoad := time.Time{}
	loadSets := func() {
		// reload at most every 5s
		if !lastLoad.IsZero() && time.Since(lastLoad) < 5*time.Second {
			return
		}
		lastLoad = time.Now()

		loadFile := func(path string) (map[string]struct{}, error) {
			f, err := os.Open(path)
			if err != nil {
				return nil, err
			}
			defer f.Close()
			b, err := io.ReadAll(f)
			if err != nil {
				return nil, err
			}
			m := map[string]struct{}{}
			for _, line := range strings.Split(string(b), "\n") {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, ";") || strings.HasPrefix(line, "$") {
					continue
				}
				// Format: domain. CNAME .
				parts := strings.Fields(line)
				if len(parts) < 1 {
					continue
				}
				d := strings.TrimSuffix(parts[0], ".")
				d = strings.ToLower(d)
				if d != "" && d != "@" {
					m[d] = struct{}{}
				}
			}
			return m, nil
		}

		if m, err := loadFile("/shared/rpz/blocklist-combined.rpz"); err == nil {
			blockedSet = m
		}
		if m, err := loadFile("/shared/rpz/whitelist.rpz"); err == nil {
			allowSet = m
		}
	}

	makeEvent := func(ts time.Time, clientIP string, qname string, qtype int, rcode int, latencyMS int) buffer.Event {
		normQName := strings.TrimSuffix(strings.ToLower(qname), ".")
		loadSets()
		_, allow := allowSet[normQName]
		_, blocked := blockedSet[normQName]
		isBlocked := blocked && !allow

		h := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%s|%s|%d|%d", cfg.NodeName, ts.Format(time.RFC3339Nano), clientIP, normQName, qtype, rcode)))
		eid := hex.EncodeToString(h[:])

		ev := buffer.Event{
			Ts:        ts.Format(time.RFC3339Nano),
			ClientIP:  clientIP,
			QName:     qname,
			QType:     qtype,
			RCode:     rcode,
			Blocked:   isBlocked,
			LatencyMS: latencyMS,
			EventID:   eid,
		}
		if isBlocked {
			ev.BlockReason = "rpz"
		}
		return ev
	}

	protobufEvents := make(chan buffer.Event, 2048)

	pbRecvTotal := 0
	pbUnmarshalErr := 0
	pbListUnmarshalErr := 0
	pbSampleLeft := 25

	// Protobuf receiver: the Recursor connects to us over TCP and sends framed protobuf payloads.
	ln, err := net.Listen("tcp", cfg.ProtobufListen)
	if err != nil {
		log.Fatalf("protobuf listen %s: %v", cfg.ProtobufListen, err)
	}
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				// keep accepting unless the listener is closed
				if ne, ok := err.(*net.OpError); ok && ne.Err != nil && strings.Contains(ne.Err.Error(), "closed") {
					return
				}
				log.Printf("protobuf accept: %v", err)
				continue
			}

			if cfg.Debug {
				log.Printf("protobuf accepted remote=%s", conn.RemoteAddr())
			}

			go func(c net.Conn) {
				defer func() { _ = c.Close() }()
				r := bufio.NewReader(c)
				ps := powerdns_protobuf.NewProtobufStream(r, c, 5*time.Second)

				processOne := func(pbdm *powerdns_protobuf.PBDNSMessage) {
					t := pbdm.GetType()

					from := net.IP(pbdm.GetFrom())
					to := net.IP(pbdm.GetTo())

					q := pbdm.GetQuestion()
					qname := ""
					qtype := 0
					if q != nil {
						qname = q.GetQName()
						qtype = int(q.GetQType())
					}

					if cfg.Debug && pbSampleLeft > 0 {
						pbSampleLeft--
						fromStr := ""
						toStr := ""
						if from != nil {
							fromStr = from.String()
						}
						if to != nil {
							toStr = to.String()
						}
						rcodeDebug := 0
						if resp := pbdm.GetResponse(); resp != nil {
							rcodeDebug = int(resp.GetRcode())
						}
						log.Printf(
							"protobuf sample type=%s from=%s:%d to=%s:%d qname=%s qtype=%d rcode=%d",
							t.String(), fromStr, pbdm.GetFromPort(), toStr, pbdm.GetToPort(), qname, qtype, rcodeDebug,
						)
					}

					// Process both queries and responses
					// Responses have latency info and rcode; queries don't
					if t != powerdns_protobuf.PBDNSMessage_DNSQueryType && t != powerdns_protobuf.PBDNSMessage_DNSResponseType {
						return
					}

					if from == nil {
						return
					}
					if q == nil || qname == "" {
						return
					}

					clientIP := from.String()

					rcode := 0
					latencyMS := 0
					ts := time.Now().UTC()

					if t == powerdns_protobuf.PBDNSMessage_DNSResponseType {
						// Response events have rcode and latency info
						resp := pbdm.GetResponse()
						if resp != nil {
							rcode = int(resp.GetRcode())

							// Calculate latency from query time in response
							queryTimeSec := resp.GetQueryTimeSec()
							queryTimeUsec := resp.GetQueryTimeUsec()
							if queryTimeSec != 0 && pbdm.GetTimeSec() != 0 {
								qts := time.Unix(int64(queryTimeSec), int64(queryTimeUsec)*1e3)
								rts := time.Unix(int64(pbdm.GetTimeSec()), int64(pbdm.GetTimeUsec())*1e3)
								if d := rts.Sub(qts); d > 0 {
									latencyMS = int(d / time.Millisecond)
								}
							}
						}
						if pbdm.GetTimeSec() != 0 {
							ts = time.Unix(int64(pbdm.GetTimeSec()), int64(pbdm.GetTimeUsec())*1e3).UTC()
						}
					} else {
						// Query events: use message timestamp, no rcode/latency
						if pbdm.GetTimeSec() != 0 {
							ts = time.Unix(int64(pbdm.GetTimeSec()), int64(pbdm.GetTimeUsec())*1e3).UTC()
						}
					}

					ev := makeEvent(ts, clientIP, qname, qtype, rcode, latencyMS)
					select {
					case protobufEvents <- ev:
					default:
						// drop under backpressure
					}
				}

				for {
					payload, err := ps.RecvPayload(false)
					if err != nil {
						if cfg.Debug {
							log.Printf("protobuf recv error: %v", err)
						}
						return
					}

					pbRecvTotal++
					data := payload.Data()
					pbdm := &powerdns_protobuf.PBDNSMessage{}
					if err := proto.Unmarshal(data, pbdm); err == nil {
						processOne(pbdm)
						continue
					}
					pbUnmarshalErr++

					// Some senders batch messages using PBDNSMessageList.
					pbl := &powerdns_protobuf.PBDNSMessageList{}
					if err := proto.Unmarshal(data, pbl); err != nil {
						pbListUnmarshalErr++
						continue
					}
					for _, m := range pbl.GetMsg() {
						if m != nil {
							processOne(m)
						}
					}
				}
			}(conn)
		}
	}()

	flushEvery := 2 * time.Second
	maxBatch := 500
	ticker := time.NewTicker(flushEvery)
	defer ticker.Stop()

	pruneEvery := 5 * time.Minute
	pruneTicker := time.NewTicker(pruneEvery)
	defer pruneTicker.Stop()

	debug := cfg.Debug
	debugTicker := time.NewTicker(10 * time.Second)
	defer debugTicker.Stop()
	recvTotal := 0
	recvByType := map[string]int{}
	debugSampleLeft := 25

	batch := make([]buffer.Event, 0, maxBatch)

	flushToBuffer := func() {
		if len(batch) == 0 {
			return
		}

		if err := buf.PutBatch(batch); err != nil {
			log.Printf("buffer put failed: %v", err)
		}
		batch = batch[:0]
	}

	forwardFromBuffer := func() {
		events, err := buf.Peek(maxBatch)
		if err != nil {
			log.Printf("buffer peek failed: %v", err)
			return
		}
		if len(events) == 0 {
			return
		}

		payload := map[string]any{"events": events}
		b, _ := json.Marshal(payload)

		req, err := http.NewRequest("POST", strings.TrimRight(cfg.Primary.URL, "/")+"/api/node-sync/ingest", bytes.NewReader(b))
		if err != nil {
			return
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-PowerBlockade-Node-Key", cfg.Primary.APIKey)

		resp, err := client.Do(req)
		if err != nil {
			log.Printf("ingest post failed (buffered %d): %v", buf.Count(), err)
			return
		}
		_ = resp.Body.Close()
		if resp.StatusCode >= 300 {
			log.Printf("ingest post status=%d (buffered %d)", resp.StatusCode, buf.Count())
			return
		}

		maxSeq := events[len(events)-1].EventSeq
		if err := buf.Delete(maxSeq); err != nil {
			log.Printf("buffer delete failed: %v", err)
		}

		if debug {
			log.Printf("ingest ok batch=%d remaining=%d", len(events), buf.Count())
		}
	}

	for {
		select {
		case <-pruneTicker.C:
			if err := buf.Prune(); err != nil {
				log.Printf("buffer prune failed: %v", err)
			}

		case <-debugTicker.C:
			if debug {
				log.Printf(
					"dnstap recv_total=%d types=%v protobuf_recv_total=%d protobuf_unmarshal_err=%d protobuf_list_unmarshal_err=%d buffered=%d",
					recvTotal, recvByType, pbRecvTotal, pbUnmarshalErr, pbListUnmarshalErr, buf.Count(),
				)
			}

		case ev := <-protobufEvents:
			batch = append(batch, ev)
			if len(batch) >= maxBatch {
				flushToBuffer()
			}

		case data, ok := <-dataChan:
			if !ok {
				log.Printf("dnstap channel closed")
				return
			}

			recvTotal++
			dt := &dnstap.Dnstap{}
			if err := proto.Unmarshal(data, dt); err != nil {
				continue
			}
			msg := dt.GetMessage()
			if msg == nil {
				continue
			}

			t := msg.GetType()
			recvByType[t.String()]++
			if debug && debugSampleLeft > 0 {
				debugSampleLeft--

				qaddr := ""
				if qa := net.IP(msg.GetQueryAddress()); qa != nil {
					qaddr = qa.String()
				}
				raddr := ""
				if ra := net.IP(msg.GetResponseAddress()); ra != nil {
					raddr = ra.String()
				}

				log.Printf(
					"dnstap sample type=%s qaddr=%s:%d raddr=%s:%d qmsg=%d rmsg=%d",
					t.String(), qaddr, msg.GetQueryPort(), raddr, msg.GetResponsePort(),
					len(msg.GetQueryMessage()), len(msg.GetResponseMessage()),
				)
			}

			if t != dnstap.Message_CLIENT_RESPONSE {
				continue
			}

			ipBytes := msg.GetQueryAddress()
			ip := net.IP(ipBytes)
			if ip == nil {
				continue
			}
			clientIP := ip.String()

			wire := msg.GetResponseMessage()
			if len(wire) == 0 {
				continue
			}

			var dnsMsg dns.Msg
			if err := dnsMsg.Unpack(wire); err != nil {
				continue
			}
			if len(dnsMsg.Question) == 0 {
				continue
			}
			qname := dnsMsg.Question[0].Name
			qtype := int(dnsMsg.Question[0].Qtype)

			rcode := dnsMsg.Rcode

			latencyMS := 0
			if msg.GetQueryTimeSec() != 0 && msg.GetResponseTimeSec() != 0 {
				qts := time.Unix(int64(msg.GetQueryTimeSec()), int64(msg.GetQueryTimeNsec()))
				rts := time.Unix(int64(msg.GetResponseTimeSec()), int64(msg.GetResponseTimeNsec()))
				if d := rts.Sub(qts); d > 0 {
					latencyMS = int(d / time.Millisecond)
				}
			}

			ts := time.Now().UTC()
			if msg.GetResponseTimeSec() != 0 {
				ts = time.Unix(int64(msg.GetResponseTimeSec()), int64(msg.GetResponseTimeNsec())).UTC()
			} else if msg.GetQueryTimeSec() != 0 {
				ts = time.Unix(int64(msg.GetQueryTimeSec()), int64(msg.GetQueryTimeNsec())).UTC()
			}

			batch = append(batch, makeEvent(ts, clientIP, qname, qtype, rcode, latencyMS))

			if len(batch) >= maxBatch {
				flushToBuffer()
			}

		case <-ticker.C:
			flushToBuffer()
			forwardFromBuffer()
		}
	}
}
