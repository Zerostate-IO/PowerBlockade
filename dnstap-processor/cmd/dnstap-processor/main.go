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

  "github.com/powerblockade/dnstap-processor/internal/config"
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
    "starting dnstap-processor node=%s dnstap_socket=%s protobuf_listen=%s primary=%s",
    cfg.NodeName, cfg.DnstapSocket, cfg.ProtobufListen, cfg.Primary.URL,
  )

  input, err := dnstap.NewFrameStreamSockInputFromPath(cfg.DnstapSocket)
  if err != nil {
    log.Fatalf("dnstap input: %v", err)
  }
  input.SetTimeout(5 * time.Second)

  // Ensure the socket is connectable by the recursor process.
  // Recursor may not run as root; allow group/other write on the socket.
  _ = os.Chmod(cfg.DnstapSocket, 0o666)

  dataChan := make(chan []byte, 2048)
  go func() {
    // ReadInto blocks; it closes channel on exit.
    input.ReadInto(dataChan)
  }()

  client := &http.Client{Timeout: 5 * time.Second}

  type event struct {
    Ts          string `json:"ts"`
    ClientIP    string `json:"client_ip"`
    QName       string `json:"qname"`
    QType       int    `json:"qtype"`
    RCode       int    `json:"rcode"`
    Blocked     bool   `json:"blocked"`
    LatencyMS   int    `json:"latency_ms,omitempty"`
    EventID     string `json:"event_id,omitempty"`
    BlockReason string `json:"block_reason,omitempty"`
  }

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

  makeEvent := func(ts time.Time, clientIP string, qname string, qtype int, rcode int, latencyMS int) event {
    normQName := strings.TrimSuffix(strings.ToLower(qname), ".")
    loadSets()
    _, allow := allowSet[normQName]
    _, blocked := blockedSet[normQName]
    isBlocked := blocked && !allow

    // event_id: stable hash (supports retry dedupe on primary)
    h := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%s|%s|%d|%d", cfg.NodeName, ts.Format(time.RFC3339Nano), clientIP, normQName, qtype, rcode)))
    eid := hex.EncodeToString(h[:])

    ev := event{
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

  protobufEvents := make(chan event, 2048)

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
            rcode := 0
            if resp := pbdm.GetResponse(); resp != nil {
              rcode = int(resp.GetRcode())
            }
            log.Printf(
              "protobuf sample type=%s from=%s:%d to=%s:%d qname=%s qtype=%d rcode=%d",
              t.String(), fromStr, pbdm.GetFromPort(), toStr, pbdm.GetToPort(), qname, qtype, rcode,
            )
          }

          // Ingest client queries only.
          if t != powerdns_protobuf.PBDNSMessage_DNSQueryType {
            return
          }

          if from == nil {
            return
          }
          if q == nil || qname == "" {
            return
          }

          clientIP := from.String()

          // Query events don't have an rcode yet.
          rcode := 0

          // Prefer message timestamp (response time).
          ts := time.Now().UTC()
          if pbdm.GetTimeSec() != 0 {
            ts = time.Unix(int64(pbdm.GetTimeSec()), int64(pbdm.GetTimeUsec())*1e3).UTC()
          }

          latencyMS := 0

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
  maxBatch := 250
  ticker := time.NewTicker(flushEvery)
  defer ticker.Stop()

  debug := cfg.Debug
  debugTicker := time.NewTicker(10 * time.Second)
  defer debugTicker.Stop()
  recvTotal := 0
  recvByType := map[string]int{}
  debugSampleLeft := 25

  batch := make([]event, 0, maxBatch)

  flush := func() {
    if len(batch) == 0 {
      return
    }

    payload := map[string]any{"events": batch}
    b, _ := json.Marshal(payload)

    req, err := http.NewRequest("POST", strings.TrimRight(cfg.Primary.URL, "/")+"/api/node-sync/ingest", bytes.NewReader(b))
    if err != nil {
      batch = batch[:0]
      return
    }
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("X-PowerBlockade-Node-Key", cfg.Primary.APIKey)

    resp, err := client.Do(req)
    if err != nil {
      log.Printf("ingest post failed: %v", err)
      return
    }
    _ = resp.Body.Close()
    if resp.StatusCode >= 300 {
      log.Printf("ingest post status=%d", resp.StatusCode)
      return
    }

    if debug {
      log.Printf("ingest ok batch=%d", len(batch))
    }

    batch = batch[:0]
  }

  for {
    select {
    case <-debugTicker.C:
      if debug {
        log.Printf(
          "dnstap recv_total=%d types=%v protobuf_recv_total=%d protobuf_unmarshal_err=%d protobuf_list_unmarshal_err=%d",
          recvTotal, recvByType, pbRecvTotal, pbUnmarshalErr, pbListUnmarshalErr,
        )
      }

    case ev := <-protobufEvents:
      batch = append(batch, ev)
      if len(batch) >= maxBatch {
        flush()
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

      // For PowerBlockade we log client-facing events only.
      // When dnsdist is the edge logger, RESOLVER_* events are internal forwarding,
      // and will show dnsdist/recursor addresses instead of the actual LAN client.
      //
      // To keep logs Pi-hole-like (one row per resolved qname/qtype), ingest responses only.
      if t != dnstap.Message_CLIENT_RESPONSE {
        continue
      }

      // For dnsdist CLIENT_* events, QueryAddress/QueryPort are the downstream client.
      // ResponseAddress/ResponsePort are the local bind address (dnsdist), not the client.
      ipBytes := msg.GetQueryAddress()
      ip := net.IP(ipBytes)
      if ip == nil {
        continue
      }
      clientIP := ip.String()

      // DNS payload: CLIENT_RESPONSE should carry ResponseMessage.
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

      // Latency (if response + query timestamps exist)
      latencyMS := 0
      if msg.GetQueryTimeSec() != 0 && msg.GetResponseTimeSec() != 0 {
        qts := time.Unix(int64(msg.GetQueryTimeSec()), int64(msg.GetQueryTimeNsec()))
        rts := time.Unix(int64(msg.GetResponseTimeSec()), int64(msg.GetResponseTimeNsec()))
        if d := rts.Sub(qts); d > 0 {
          latencyMS = int(d / time.Millisecond)
        }
      }

      // Prefer response timestamp; fall back to query timestamp; fall back to now.
      ts := time.Now().UTC()
      if msg.GetResponseTimeSec() != 0 {
        ts = time.Unix(int64(msg.GetResponseTimeSec()), int64(msg.GetResponseTimeNsec())).UTC()
      } else if msg.GetQueryTimeSec() != 0 {
        ts = time.Unix(int64(msg.GetQueryTimeSec()), int64(msg.GetQueryTimeNsec())).UTC()
      }

      // event_id: stable hash (supports retry dedupe on primary)
      batch = append(batch, makeEvent(ts, clientIP, qname, qtype, rcode, latencyMS))

      if len(batch) >= maxBatch {
        flush()
      }

    case <-ticker.C:
      flush()
    }
  }
}
