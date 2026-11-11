package app

import "testing"

func TestUniqueCarryKeepsOneEntryPerTicket(t *testing.T) {
	got := planUniqueCarry([]CarryInput{{Ticket: "A-1", Rest: 2}, {Ticket: "B-1", Rest: 1}, {Ticket: "A-1", Rest: 2}, {Ticket: "A-1", Rest: 0.5}})
	if len(got) != 2 || got[0].Ticket != "A-1" || got[0].Rest != 0.5 || got[1].Ticket != "B-1" {
		t.Fatalf("carry = %+v", got)
	}
}
