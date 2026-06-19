from simulation_engine.recorder_models import ParsedAlert, RecorderSettings, normalize_contract_key


def test_recorder_settings_masks_token():
    settings = RecorderSettings(discord_token="secret-token", discord_channel_ids=["123"])

    masked = settings.masked()

    assert masked.discord_token == "********"
    assert masked.discord_channel_ids == ["123"]


def test_contract_key_normalization():
    assert normalize_contract_key("spy", "6/21/2026", 500, "call") == "SPY|2026-06-21|500|CALL"


def test_parsed_alert_accepts_unparsed_message():
    alert = ParsedAlert(message_id="m1", parse_status="unparsed", raw_text="watching SPY")

    assert alert.parse_status == "unparsed"
    assert alert.ticker is None
