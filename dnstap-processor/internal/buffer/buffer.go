package buffer

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	bolt "go.etcd.io/bbolt"
)

var eventsBucket = []byte("events")

type Event struct {
	EventSeq    uint64 `json:"event_seq"`
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

type Buffer struct {
	db       *bolt.DB
	seq      uint64
	maxBytes int64
	maxAge   time.Duration
	mu       sync.Mutex
}

func Open(path string, maxBytes int64, maxAgeSeconds int) (*Buffer, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create buffer dir: %w", err)
	}

	db, err := bolt.Open(path, 0o600, &bolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, fmt.Errorf("open bolt db: %w", err)
	}

	err = db.Update(func(tx *bolt.Tx) error {
		_, err := tx.CreateBucketIfNotExists(eventsBucket)
		return err
	})
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("create bucket: %w", err)
	}

	var maxSeq uint64
	db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket(eventsBucket)
		if b == nil {
			return nil
		}
		c := b.Cursor()
		k, _ := c.Last()
		if k != nil {
			maxSeq = binary.BigEndian.Uint64(k)
		}
		return nil
	})

	return &Buffer{
		db:       db,
		seq:      maxSeq,
		maxBytes: maxBytes,
		maxAge:   time.Duration(maxAgeSeconds) * time.Second,
	}, nil
}

func (b *Buffer) Close() error {
	return b.db.Close()
}

func (b *Buffer) NextSeq() uint64 {
	return atomic.AddUint64(&b.seq, 1)
}

func (b *Buffer) Put(ev Event) error {
	ev.EventSeq = b.NextSeq()

	data, err := json.Marshal(ev)
	if err != nil {
		return err
	}

	key := make([]byte, 8)
	binary.BigEndian.PutUint64(key, ev.EventSeq)

	return b.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		return bucket.Put(key, data)
	})
}

func (b *Buffer) PutBatch(events []Event) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	return b.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		for i := range events {
			events[i].EventSeq = atomic.AddUint64(&b.seq, 1)
			data, err := json.Marshal(events[i])
			if err != nil {
				continue
			}
			key := make([]byte, 8)
			binary.BigEndian.PutUint64(key, events[i].EventSeq)
			if err := bucket.Put(key, data); err != nil {
				return err
			}
		}
		return nil
	})
}

func (b *Buffer) Peek(limit int) ([]Event, error) {
	var events []Event

	err := b.db.View(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		if bucket == nil {
			return nil
		}

		c := bucket.Cursor()
		count := 0
		for k, v := c.First(); k != nil && count < limit; k, v = c.Next() {
			var ev Event
			if err := json.Unmarshal(v, &ev); err != nil {
				continue
			}
			events = append(events, ev)
			count++
		}
		return nil
	})

	return events, err
}

func (b *Buffer) Delete(upToSeq uint64) error {
	return b.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		if bucket == nil {
			return nil
		}

		c := bucket.Cursor()
		for k, _ := c.First(); k != nil; k, _ = c.Next() {
			seq := binary.BigEndian.Uint64(k)
			if seq > upToSeq {
				break
			}
			if err := bucket.Delete(k); err != nil {
				return err
			}
		}
		return nil
	})
}

func (b *Buffer) Count() int {
	var count int
	b.db.View(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		if bucket != nil {
			count = bucket.Stats().KeyN
		}
		return nil
	})
	return count
}

func (b *Buffer) Prune() error {
	if b.maxAge <= 0 {
		return nil
	}

	cutoff := time.Now().Add(-b.maxAge)
	var toDelete [][]byte

	err := b.db.View(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		if bucket == nil {
			return nil
		}

		c := bucket.Cursor()
		for k, v := c.First(); k != nil; k, v = c.Next() {
			var ev Event
			if err := json.Unmarshal(v, &ev); err != nil {
				toDelete = append(toDelete, append([]byte{}, k...))
				continue
			}
			ts, err := time.Parse(time.RFC3339Nano, ev.Ts)
			if err != nil {
				continue
			}
			if ts.Before(cutoff) {
				toDelete = append(toDelete, append([]byte{}, k...))
			}
		}
		return nil
	})
	if err != nil {
		return err
	}

	if len(toDelete) == 0 {
		return nil
	}

	log.Printf("buffer: pruning %d old events", len(toDelete))

	return b.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(eventsBucket)
		for _, k := range toDelete {
			if err := bucket.Delete(k); err != nil {
				return err
			}
		}
		return nil
	})
}

func (b *Buffer) SizeBytes() int64 {
	info, err := os.Stat(b.db.Path())
	if err != nil {
		return 0
	}
	return info.Size()
}
