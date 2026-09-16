import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from load_csv_to_adls import read_and_validate
from sources import AMEYO_CALLS, PAYMENTS


def test_read_and_validate_splits_valid_and_rejected_rows(tmp_path):
    csv_content = (
        "ch_call_id,ch_date_added,ch_contact_center_id,ch_system_disposition,"
        "ch_call_type,total_talk_time,udh_user_id,campaign_name,udh_notes\n"
        "call-1,2026-08-05 06:57:26.609,1,CONNECTED,click.to.call.dial,96250,"
        "grace.alweny,OPEN VOX-GSM,71667828\n"
        # malformed: one extra bare comma, so field count won't match the header
        "call-2,2026-08-05 06:58:46.024,1,CONNECTED,click.to.call.dial,131003,"
        "user,CAMPAIGN,note,extra,field\n"
    )
    path = tmp_path / "Outbound Calls Ameyo.csv"
    path.write_text(csv_content, encoding="utf-8")

    valid_rows, rejects = read_and_validate(AMEYO_CALLS, path)

    assert len(valid_rows) == 1
    # Raw is raw: values land untouched, as literal strings -- no casting.
    assert valid_rows[0]["ch_call_id"] == "call-1"
    assert valid_rows[0]["ch_contact_center_id"] == "1"
    assert len(rejects) == 1
    assert rejects[0]["line_number"] == 3


def test_empty_cells_stay_as_empty_strings_not_null(tmp_path):
    csv_content = (
        "ch_call_id,ch_date_added,ch_contact_center_id,ch_system_disposition,"
        "ch_call_type,total_talk_time,udh_user_id,campaign_name,udh_notes\n"
        "call-1,2026-08-05 06:57:26.609,1,CONNECTED,click.to.call.dial,96250,"
        "grace.alweny,OPEN VOX-GSM,\n"
    )
    path = tmp_path / "Outbound Calls Ameyo.csv"
    path.write_text(csv_content, encoding="utf-8")

    valid_rows, _ = read_and_validate(AMEYO_CALLS, path)

    assert valid_rows[0]["udh_notes"] == ""  # literal, not None/NULL


def test_duplicate_natural_keys_within_a_file_all_survive(tmp_path):
    """Raw is an append-only landing log, not an upsert target: if the
    source file itself contains two rows sharing the same ch_call_id (as
    Outbound Calls Ameyo.csv does, via a stray-quote CSV artifact), both
    rows must load -- raw must not silently pick a winner. Deduplication is
    a staging-layer decision, not an ingestion-layer one.
    """
    csv_content = (
        "ch_call_id,ch_date_added,ch_contact_center_id,ch_system_disposition,"
        "ch_call_type,total_talk_time,udh_user_id,campaign_name,udh_notes\n"
        "dup-1,2026-08-05 06:57:26.609,1,CONNECTED,click.to.call.dial,96250,agent.a,C1,note-a\n"
        "dup-1,2026-08-05 07:10:00.000,1,CONNECTED,click.to.call.dial,50000,agent.b,C1,note-b\n"
    )
    path = tmp_path / "Outbound Calls Ameyo.csv"
    path.write_text(csv_content, encoding="utf-8")

    valid_rows, rejects = read_and_validate(AMEYO_CALLS, path)

    assert not rejects
    assert len(valid_rows) == 2  # neither duplicate row is dropped
    assert {r["udh_notes"] for r in valid_rows} == {"note-a", "note-b"}


def test_payments_transform_row_adds_stable_synthetic_key(tmp_path):
    csv_content = (
        "pay_timestamp_utc,tenant_id,contract_id,payment_request_provider,create_program,amount\n"
        "2026-08-05 09:59:48.000,1004,4273196,Monnify Nigeria,paymentsintegrationservicemonnifyng,5890.0\n"
    )
    path = tmp_path / "Payments Data Atlas.csv"
    path.write_text(csv_content, encoding="utf-8")

    valid_rows, rejects = read_and_validate(PAYMENTS, path)

    assert not rejects
    key_a = valid_rows[0]["_payment_row_key"]

    # Re-parsing the identical row must produce the identical key -- this
    # key exists so dbt staging can recognize/dedupe exact-duplicate
    # payments deterministically; ingestion itself does not act on it.
    valid_rows_again, _ = read_and_validate(PAYMENTS, path)
    assert valid_rows_again[0]["_payment_row_key"] == key_a
