package buffer

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestBufferOpenClose(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}

	if buf.Count() != 0 {
		t.Errorf("Count() = %d, want 0 for new buffer", buf.Count())
	}

	if err := buf.Close(); err != nil {
		t.Errorf("Close() error: %v", err)
	}

	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		t.Error("database file should exist after Open")
	}
}

func TestBufferPutAndPeek(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	ev := Event{
		Ts:       time.Now().Format(time.RFC3339Nano),
		ClientIP: "192.168.1.100",
		QName:    "example.com",
		QType:    1,
		RCode:    0,
		Blocked:  false,
	}

	if err := buf.Put(ev); err != nil {
		t.Fatalf("Put() error: %v", err)
	}

	if buf.Count() != 1 {
		t.Errorf("Count() = %d, want 1", buf.Count())
	}

	events, err := buf.Peek(10)
	if err != nil {
		t.Fatalf("Peek() error: %v", err)
	}

	if len(events) != 1 {
		t.Fatalf("Peek() returned %d events, want 1", len(events))
	}

	if events[0].ClientIP != "192.168.1.100" {
		t.Errorf("ClientIP = %q, want %q", events[0].ClientIP, "192.168.1.100")
	}
	if events[0].QName != "example.com" {
		t.Errorf("QName = %q, want %q", events[0].QName, "example.com")
	}
	if events[0].EventSeq == 0 {
		t.Error("EventSeq should be assigned")
	}
}

func TestBufferPutBatch(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	events := []Event{
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.1", QName: "a.com", QType: 1, RCode: 0},
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.2", QName: "b.com", QType: 1, RCode: 0},
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.3", QName: "c.com", QType: 1, RCode: 0},
	}

	if err := buf.PutBatch(events); err != nil {
		t.Fatalf("PutBatch() error: %v", err)
	}

	if buf.Count() != 3 {
		t.Errorf("Count() = %d, want 3", buf.Count())
	}

	peeked, err := buf.Peek(10)
	if err != nil {
		t.Fatalf("Peek() error: %v", err)
	}

	if len(peeked) != 3 {
		t.Fatalf("Peek() returned %d events, want 3", len(peeked))
	}

	for i, ev := range peeked {
		if ev.EventSeq == 0 {
			t.Errorf("events[%d].EventSeq should be assigned", i)
		}
	}
}

func TestBufferDelete(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	events := []Event{
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.1", QName: "a.com", QType: 1, RCode: 0},
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.2", QName: "b.com", QType: 1, RCode: 0},
		{Ts: time.Now().Format(time.RFC3339Nano), ClientIP: "10.0.0.3", QName: "c.com", QType: 1, RCode: 0},
	}
	buf.PutBatch(events)

	peeked, _ := buf.Peek(10)
	if len(peeked) < 2 {
		t.Fatal("need at least 2 events")
	}

	deleteUpTo := peeked[1].EventSeq
	if err := buf.Delete(deleteUpTo); err != nil {
		t.Fatalf("Delete() error: %v", err)
	}

	if buf.Count() != 1 {
		t.Errorf("Count() = %d after Delete, want 1", buf.Count())
	}

	remaining, _ := buf.Peek(10)
	if len(remaining) != 1 {
		t.Fatalf("Peek() returned %d events after Delete, want 1", len(remaining))
	}
	if remaining[0].QName != "c.com" {
		t.Errorf("remaining event QName = %q, want %q", remaining[0].QName, "c.com")
	}
}

func TestBufferNextSeq(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	seq1 := buf.NextSeq()
	seq2 := buf.NextSeq()
	seq3 := buf.NextSeq()

	if seq2 != seq1+1 {
		t.Errorf("seq2 = %d, want %d", seq2, seq1+1)
	}
	if seq3 != seq2+1 {
		t.Errorf("seq3 = %d, want %d", seq3, seq2+1)
	}
}

func TestBufferPeekLimit(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	for i := 0; i < 10; i++ {
		buf.Put(Event{Ts: time.Now().Format(time.RFC3339Nano), QName: "test.com"})
	}

	events, err := buf.Peek(5)
	if err != nil {
		t.Fatalf("Peek() error: %v", err)
	}

	if len(events) != 5 {
		t.Errorf("Peek(5) returned %d events, want 5", len(events))
	}
}

func TestBufferSizeBytes(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}
	defer buf.Close()

	initialSize := buf.SizeBytes()
	if initialSize <= 0 {
		t.Error("SizeBytes() should be > 0 after Open")
	}

	for i := 0; i < 100; i++ {
		buf.Put(Event{
			Ts:       time.Now().Format(time.RFC3339Nano),
			ClientIP: "192.168.1.100",
			QName:    "verylongdomainname.example.com",
			QType:    1,
			RCode:    0,
		})
	}

	afterSize := buf.SizeBytes()
	if afterSize <= initialSize {
		t.Errorf("SizeBytes() should increase after adding events, got %d <= %d", afterSize, initialSize)
	}
}

func TestBufferPersistence(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test.db")

	buf1, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() error: %v", err)
	}

	buf1.Put(Event{Ts: time.Now().Format(time.RFC3339Nano), QName: "persist.com", ClientIP: "1.2.3.4"})
	buf1.Close()

	buf2, err := Open(dbPath, 10*1024*1024, 3600)
	if err != nil {
		t.Fatalf("Open() for re-open error: %v", err)
	}
	defer buf2.Close()

	if buf2.Count() != 1 {
		t.Errorf("Count() after reopen = %d, want 1", buf2.Count())
	}

	events, _ := buf2.Peek(10)
	if len(events) != 1 || events[0].QName != "persist.com" {
		t.Error("Event should persist across close/reopen")
	}
}
