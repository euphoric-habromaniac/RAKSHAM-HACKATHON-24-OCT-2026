"""L3 digit challenge: generation, Hindi/English digit parsing, reply time."""
import pytest

from service import challenge as ch
from service.config import ChallengeConfig
from service.models import L3Outcome

CFG = ChallengeConfig(digits=6, min_reply_seconds=1.0, max_reply_seconds=15.0)


# --------------------------------------------------------------- generation
def test_generation_length_and_alphabet():
    for _ in range(50):
        d = ch.generate_digits(6)
        assert len(d) == 6 and d.isdigit()


def test_generation_uses_secrets_module(monkeypatch):
    calls = []
    monkeypatch.setattr(ch.secrets, "choice", lambda seq: calls.append(seq) or "7")
    assert ch.generate_digits(6) == "777777"
    assert len(calls) == 6


def test_generation_is_not_constant():
    assert len({ch.generate_digits(6) for _ in range(30)}) > 1


def test_agent_format_spaces_digits():
    assert ch.format_for_agent("491703") == "4 9 1 7 0 3"


# ------------------------------------------------------------ normalisation
@pytest.mark.parametrize("text,expected", [
    ("4 9 1 7 0 3", "491703"),
    ("491703", "491703"),
    ("4-9-1, 7. 0 3", "491703"),
    ("four nine one seven zero three", "491703"),
    ("Four Nine One Seven Zero Three", "491703"),
    ("the digits are four nine one seven zero three thanks", "491703"),
    ("४ ९ १ ७ ० ३", "491703"),
    ("४९१७०३", "491703"),
    ("char nau ek saat shunya teen", "491703"),
    ("chaar nau ek saat zero teen", "491703"),
    ("ek do teen char paanch chhah", "123456"),
    ("ek do teen char panch chhe", "123456"),
    ("saat aath nau shunya ek do", "789012"),
    ("चार नौ एक सात शून्य तीन", "491703"),
    ("एक दो तीन चार पांच छह", "123456"),
    ("सात आठ नौ जीरो एक दो", "789012"),
    ("char 9 ek सात zero तीन", "491703"),
    ("double teen char paanch chhe ek", "334561"),
    ("triple ek char paanch", "11145"),
])
def test_normalise_digits(text, expected):
    assert "".join(ch.normalise_digits(text)) == expected


def test_normalise_ignores_text_without_digits():
    assert ch.normalise_digits("I do not know what you mean") == ["2"]  # 'do' is Hindi for 2
    assert ch.normalise_digits("") == []
    assert ch.normalise_digits("haan ji bataiye") == []


# --------------------------------------------------------------- evaluation
def issue(digits="491703", at=100.0):
    return ch.Challenge(digits=digits, issued_at=at)


def test_correct_digits_in_time_pass():
    r = ch.evaluate(issue(), "4 9 1 7 0 3", 105.0, CFG)
    assert r.outcome is L3Outcome.PASS and r.reply_seconds == 5.0


def test_correct_digits_spoken_in_hindi_pass():
    assert ch.evaluate(issue(), "char nau ek saat shunya teen", 105.0, CFG).outcome is L3Outcome.PASS
    assert ch.evaluate(issue(), "चार नौ एक सात शून्य तीन", 105.0, CFG).outcome is L3Outcome.PASS


def test_wrong_digits_fail():
    r = ch.evaluate(issue(), "4 9 1 7 0 4", 105.0, CFG)
    assert r.outcome is L3Outcome.FAIL and r.reason == "digits_mismatch"


def test_right_digits_wrong_order_fail():
    assert ch.evaluate(issue(), "9 4 1 7 0 3", 105.0, CFG).outcome is L3Outcome.FAIL


def test_too_few_or_too_many_digits_unclear():
    assert ch.evaluate(issue(), "4 9 1", 105.0, CFG).outcome is L3Outcome.UNCLEAR
    assert ch.evaluate(issue(), "4 9 1 7 0 3 5", 105.0, CFG).outcome is L3Outcome.UNCLEAR


def test_no_digits_unclear():
    assert ch.evaluate(issue(), "umm sorry what", 105.0, CFG).outcome is L3Outcome.UNCLEAR
    assert ch.evaluate(issue(), "", 105.0, CFG).outcome is L3Outcome.UNCLEAR


def test_reply_too_slow_fails_even_if_digits_match():
    r = ch.evaluate(issue(), "4 9 1 7 0 3", 100.0 + 15.01, CFG)
    assert r.outcome is L3Outcome.FAIL and r.reason == "reply_too_slow"


def test_reply_at_limit_passes():
    assert ch.evaluate(issue(), "491703", 115.0, CFG).outcome is L3Outcome.PASS


def test_reply_too_fast_fails():
    r = ch.evaluate(issue(), "491703", 100.2, CFG)
    assert r.outcome is L3Outcome.FAIL and r.reason == "reply_too_fast"


def test_new_challenge_uses_config_length():
    c = ch.new_challenge(ChallengeConfig(digits=8), now=5.0)
    assert len(c.digits) == 8 and c.issued_at == 5.0
