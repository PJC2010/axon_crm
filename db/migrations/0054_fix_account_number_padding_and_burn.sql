-- Migration 0054: fix two defects in customer account-number assignment.
--
-- Both live in the assign_account_number() trigger from migration 038.
--
-- #1  LPAD truncation (data-corrupting, was breaking seeds).
--     The old body formatted numbers as 'C-' || LPAD(consumed::TEXT, 5, '0').
--     Postgres LPAD *truncates* a string that is already longer than the target
--     width, so once a per-org counter crossed 99999 the number was silently
--     mangled: consumed=125765 -> LPAD('125765',5) = '12576' -> 'C-12576',
--     which collided with the real C-12576 assigned back when the counter was
--     ~12576. The colliding INSERT aborted the whole seed transaction.
--     Fix: LPAD(consumed::TEXT, GREATEST(5, LENGTH(consumed::TEXT)), '0') —
--     pads to a MINIMUM of 5 digits and widens for longer numbers, so it never
--     truncates. (TO_CHAR with a fixed '00000' mask is NOT a fix: it returns
--     '#####' on overflow, re-breaking at the same 99999 cliff.)
--
-- #2  Counter burn on ON CONFLICT re-upserts (why any org reached the 99999
--     cliff in the first place). upsert_properties() uses
--     INSERT ... ON CONFLICT (account_id, address, zip) DO UPDATE. A BEFORE
--     INSERT trigger fires for EVERY proposed row — including the ones that go
--     on to take the DO UPDATE path — so every enrichment re-upsert of an
--     already-seeded ZIP consumed a fresh counter value per row and threw it
--     away. A single org with ~42k leads had burned its counter past 125000.
--     Fix: before drawing a new number, look up the existing lead at the same
--     (account_id, address, zip) key and reuse its number. Only a genuinely new
--     lead advances the counter; re-upserts consume nothing and no longer lock
--     the accounts row. Assignment stays in BEFORE INSERT, so every INSERT ...
--     RETURNING account_number path keeps returning a populated value.

CREATE OR REPLACE FUNCTION assign_account_number()
RETURNS TRIGGER AS $$
DECLARE
    consumed INT;
    existing TEXT;
BEGIN
    IF NEW.account_number IS NULL THEN
        -- Reuse the number already held by a lead at this conflict key so an
        -- ON CONFLICT re-upsert (enrichment, re-import) does not burn a number.
        SELECT account_number INTO existing
          FROM properties
         WHERE account_id = NEW.account_id
           AND address = NEW.address
           AND zip = NEW.zip
         LIMIT 1;

        IF existing IS NOT NULL THEN
            NEW.account_number := existing;
        ELSE
            -- Genuinely new lead: draw the next per-org number. The UPDATE locks
            -- the account row, serializing concurrent inserts for the same org.
            UPDATE accounts
               SET next_customer_no = next_customer_no + 1
             WHERE id = NEW.account_id
            RETURNING next_customer_no - 1 INTO consumed;
            -- Min-width 5, widening for longer numbers: never truncates (LPAD
            -- to a fixed width would) and never overflows to '#' (TO_CHAR would).
            NEW.account_number := 'C-' || LPAD(consumed::TEXT,
                                                GREATEST(5, LENGTH(consumed::TEXT)), '0');
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger definition itself is unchanged (still BEFORE INSERT FOR EACH ROW from
-- migration 038); only the function body is replaced above.
