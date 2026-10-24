"""Band policy, calibration, L4 context rules and config validation."""
import math

import pytest

from service.calibration import Platt, fit_platt
from service.config import ServiceConfig, load_config
from service.models import BankFlags, Band, L3Outcome, Strength
from service import policy

CFG = load_config()
THR = {k: policy.Thresholds(v.weak, v.strong) for k, v in CFG.layers.items()}
SENSITIVE = CFG.sensitive_request_types

LOW, WEAK, STRONG = 0.05, 0.50, 0.90  # probabilities clear of every placeholder threshold


def decide(request="balance", enrolled=True, l1=LOW, l2=LOW, l4=LOW, l3=None):
    return policy.decide(request, enrolled, {"l1": l1, "l2": l2, "l4": l4}, THR, SENSITIVE, l3)


# ------------------------------------------------------------------ bands
def test_all_quiet_is_clear():
    assert decide().band is Band.CLEAR


@pytest.mark.parametrize("layer", ["l1", "l2", "l4"])
def test_one_weak_signal_is_never_hold(layer):
    d = decide(**{layer: WEAK})
    assert d.band is Band.CLEAR
    assert d.strengths[layer] is Strength.WEAK


@pytest.mark.parametrize("layer", ["l1", "l2", "l4"])
def test_one_weak_signal_on_sensitive_request_is_step_up_not_hold(layer):
    d = decide(request="limit_change", **{layer: WEAK})
    assert d.band is Band.STEP_UP


@pytest.mark.parametrize("pair", [("l1", "l2"), ("l1", "l4"), ("l2", "l4")])
def test_two_weak_signals_step_up(pair):
    d = decide(**{pair[0]: WEAK, pair[1]: WEAK})
    assert d.band is Band.STEP_UP
    assert d.needs_challenge and not d.needs_app_prompt
    assert "two_weak_signals" in d.reasons


@pytest.mark.parametrize("layer", ["l1", "l2", "l4"])
def test_one_strong_signal_step_up(layer):
    d = decide(**{layer: STRONG})
    assert d.band is Band.STEP_UP
    assert d.reasons == ["one_strong_signal"]


def test_strong_plus_weak_is_step_up_not_hold():
    assert decide(l1=STRONG, l2=WEAK).band is Band.STEP_UP


@pytest.mark.parametrize("pair", [("l1", "l2"), ("l1", "l4"), ("l2", "l4")])
def test_two_strong_signals_hold(pair):
    d = decide(**{pair[0]: STRONG, pair[1]: STRONG})
    assert d.band is Band.HOLD
    assert d.needs_app_prompt and not d.needs_challenge


@pytest.mark.parametrize("req", ["limit_change", "new_payee", "mobile_change", "device_change"])
def test_sensitive_request_alone_is_step_up(req):
    d = decide(request=req)
    assert d.band is Band.STEP_UP
    assert d.reasons == ["sensitive_request"]


def test_non_sensitive_request_names_do_not_trigger_step_up():
    assert decide(request="balance").band is Band.CLEAR
    assert decide(request="other").band is Band.CLEAR


def test_sensitive_with_two_strong_is_hold():
    assert decide(request="new_payee", l2=STRONG, l4=STRONG).band is Band.HOLD


@pytest.mark.parametrize("outcome", [L3Outcome.FAIL, L3Outcome.UNCLEAR])
def test_l3_fail_or_unclear_is_hold(outcome):
    d = decide(request="limit_change", l3=outcome)
    assert d.band is Band.HOLD and d.needs_app_prompt


def test_l3_failure_holds_even_with_no_scored_signal():
    assert decide(l3=L3Outcome.FAIL).band is Band.HOLD


def test_l3_pass_leaves_step_up_and_does_not_reissue_challenge():
    d = decide(request="limit_change", l3=L3Outcome.PASS)
    assert d.band is Band.STEP_UP and not d.needs_challenge


# ------------------------------------------------------------ not enrolled
def test_not_enrolled_ignores_l1_entirely():
    d = decide(enrolled=False, l1=0.99)
    assert d.band is Band.CLEAR
    assert "l1" not in d.strengths


def test_not_enrolled_two_strong_among_l2_l4_holds():
    assert decide(enrolled=False, l2=STRONG, l4=STRONG).band is Band.HOLD


def test_not_enrolled_l1_cannot_supply_a_second_strong_signal():
    assert decide(enrolled=False, l1=STRONG, l2=STRONG).band is Band.STEP_UP


def test_not_enrolled_sensitive_goes_to_app_confirmation():
    d = decide(request="mobile_change", enrolled=False)
    assert d.band is Band.HOLD
    assert d.needs_app_prompt
    assert d.reasons == ["not_enrolled_sensitive_request"]


def test_not_enrolled_non_sensitive_one_weak_is_clear():
    assert decide(enrolled=False, l2=WEAK).band is Band.CLEAR


# --------------------------------------------------------------- thresholds
def test_classification_boundaries_are_inclusive():
    t = policy.Thresholds(0.3, 0.7)
    assert policy.classify(0.2999, t) is Strength.NONE
    assert policy.classify(0.3, t) is Strength.WEAK
    assert policy.classify(0.6999, t) is Strength.WEAK
    assert policy.classify(0.7, t) is Strength.STRONG


def test_thresholds_must_be_ordered():
    with pytest.raises(ValueError):
        policy.Thresholds(0.7, 0.3)


# -------------------------------------------------------------- calibration
def test_platt_known_values():
    p = Platt(a=2.0, b=-1.0)
    assert p(0.5) == pytest.approx(0.5)
    assert p(1.0) == pytest.approx(1 / (1 + math.exp(-1.0)))


def test_platt_stable_at_extremes_and_monotone():
    p = Platt(a=50.0, b=0.0)
    assert p(-1e4) == 0.0 and p(1e4) == 1.0
    assert Platt(-12, 7)(0.8) < Platt(-12, 7)(0.5)


def test_fit_platt_recovers_direction():
    scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
    labels = [0, 0, 0, 1, 1, 1]
    fitted = fit_platt(scores, labels, iters=3000, lr=0.5)
    assert fitted.a > 0 and fitted(0.9) > 0.5 > fitted(0.1)


# ----------------------------------------------------------------- L4 rules
def raw(text="", **flags):
    return policy.context_raw_score(BankFlags(**flags), text, CFG.l4)


def test_context_flags_add_weight():
    assert raw()[0] == 0.0
    assert raw(new_device=True)[0] == 1.0
    assert raw(new_device=True, new_payee=True, amount_jump=True)[0] == 3.0


@pytest.mark.parametrize("text,term", [
    ("this is urgent please", "urgent"),
    ("jaldi karo yaar", "jaldi"),
    ("abhi ke abhi chahiye", "abhi ke abhi"),
    ("warna account block ho jayega", "block ho jayega"),
    ("Please do it RIGHT   NOW", "right now"),
    ("जल्दी करो", "जल्दी"),
    ("ब्लॉक हो जाएगा", "ब्लॉक हो जाएगा"),
])
def test_urgency_terms_english_hinglish_devanagari(text, term):
    assert term in raw(text)[1]


def test_urgency_matches_whole_words_only():
    assert "abhi" not in raw("abhimanyu from the branch")[1]


def test_urgency_contribution_is_capped():
    text = "urgent immediately jaldi turant emergency block ho jayega"
    assert raw(text)[0] == CFG.l4.urgency_cap


def test_flags_plus_urgency_reach_strong_with_placeholders():
    r, _ = raw("urgent jaldi", new_device=True, new_payee=True)
    p = Platt.from_config(CFG.layers["l4"].platt)(r)
    assert policy.classify(p, THR["l4"]) is Strength.STRONG


# ------------------------------------------------------------------- config
def test_shipped_config_is_marked_placeholder():
    assert CFG.placeholder is True
    assert CFG.version.startswith("placeholder")
    assert CFG.deadline_seconds == 10.0


def test_config_rejects_unordered_thresholds():
    data = CFG.model_dump()
    data["layers"]["l2"]["weak"], data["layers"]["l2"]["strong"] = 0.9, 0.2
    with pytest.raises(ValueError):
        ServiceConfig.model_validate(data)


def test_config_requires_all_layers():
    data = CFG.model_dump()
    del data["layers"]["l4"]
    with pytest.raises(ValueError):
        ServiceConfig.model_validate(data)


def test_config_loads_from_json_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(CFG.model_dump_json(), encoding="utf-8")
    assert load_config(p).version == CFG.version
