# Poligon — test-only dummy plugins, one well-behaved plugin per slot plus
# misbehaving variants. Standalone on purpose: no Poligon imports.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import hashlib
import hmac

API = "1.0"
SALT = b"dummy-salt"


def flag_hash(answer: str) -> str:
    digest = hmac.new(SALT, answer.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


class _Plugin:
    slot = ""

    def __init__(self, name, api=API, version="0.0.1"):
        self.PLUGIN_API = api
        self.NAME = name
        self.VERSION = version

    def describe(self):
        return {"name": self.NAME, "version": self.VERSION,
                "api": self.PLUGIN_API, "slot": self.slot}


# --- scenario providers ----------------------------------------------------


def _item(set_id, number, record, **overrides):
    item = {
        "challenge_id": f"MGD-{set_id}-{number:02d}",
        "title": f"Dummy item {number}",
        "prompt": "Find the value recorded at the cited point of entry.",
        "points": 100,
        "flag_hash": flag_hash(record["raw_value"]),
        "answers": [record["raw_value"]],
        "poe_refs": [record["poe_id"]],
    }
    item.update(overrides)
    return item


class Provider(_Plugin):
    slot = "scenario_provider"

    def provide(self, context, inventory):
        items = [_item(context["set_id"], n, rec)
                 for n, rec in enumerate(inventory, 1)]
        # Inputs are copies: changing them must not reach the host.
        context.clear()
        inventory.clear()
        return items


class ProviderRaises(Provider):
    def provide(self, context, inventory):
        raise RuntimeError("dummy provider failure")


class ProviderNotAList(Provider):
    def provide(self, context, inventory):
        return {"not": "a list"}


class ProviderInvalidItem(Provider):
    """One valid item, then items that break the challenge schema."""

    def provide(self, context, inventory):
        good = super().provide(context, inventory)[:1]
        return good + [{"title": "missing fields"},
                       {**good[0], "flag_hash": "not-a-hash"},
                       "not even a dict"]


class ProviderLeaksAnswer(Provider):
    """One valid item, then items whose solver-visible text holds the answer."""

    def provide(self, context, inventory):
        good = super().provide(context, inventory)[:1]
        answer = good[0]["answers"][0]
        return good + [
            {**good[0], "challenge_id": good[0]["challenge_id"][:-2] + "90",
             "title": f"The answer is {answer}"},
            {**good[0], "challenge_id": good[0]["challenge_id"][:-2] + "91",
             "prompt": f"Submit {answer.upper()} to score"},
        ]


class ProviderUnsourced(Provider):
    """One valid item, then items whose answers no cited record holds."""

    def provide(self, context, inventory):
        good = super().provide(context, inventory)[:1]
        return good + [
            {**good[0], "challenge_id": good[0]["challenge_id"][:-2] + "90",
             "answers": ["invented-value"]},
            {**good[0], "challenge_id": good[0]["challenge_id"][:-2] + "91",
             "poe_refs": ["POE-DUMMY-9999"]},
        ]


provider = Provider("dummy-provider")
provider_api2 = Provider("dummy-provider-api2", api="2.0")
provider_raises = ProviderRaises("dummy-provider-raises")
provider_not_a_list = ProviderNotAList("dummy-provider-not-a-list")
provider_invalid_item = ProviderInvalidItem("dummy-provider-invalid-item")
provider_leaks_answer = ProviderLeaksAnswer("dummy-provider-leaks-answer")
provider_unsourced = ProviderUnsourced("dummy-provider-unsourced")
# NAME differs from the entry-point name it is registered under.
provider_renamed = Provider("dummy-provider-other-name")


# --- scorers ---------------------------------------------------------------


class Scorer(_Plugin):
    slot = "scorer"

    def score(self, item, submission):
        correct = submission.get("answer") in item["answers"]
        result = {"points": item["points"] if correct else 0,
                  "max_points": item["points"],
                  "detail": "correct" if correct else "incorrect"}
        # Inputs are copies: changing them must not reach the host.
        item["answers"].clear()
        submission.clear()
        return result


class ScorerRaises(Scorer):
    def score(self, item, submission):
        raise RuntimeError("dummy scorer failure")


class ScorerInvalid(Scorer):
    def score(self, item, submission):
        return {"points": "lots", "max_points": 100, "detail": "?"}


class ScorerOutOfRange(Scorer):
    def score(self, item, submission):
        return {"points": item["points"] + 50, "max_points": item["points"],
                "detail": "generous"}


class ScorerLeaksAnswer(Scorer):
    def score(self, item, submission):
        return {"points": 0, "max_points": item["points"],
                "detail": f"incorrect; expected {item['answers'][0]}"}


scorer = Scorer("dummy-scorer")
scorer_api2 = Scorer("dummy-scorer-api2", api="2.0")
scorer_raises = ScorerRaises("dummy-scorer-raises")
scorer_invalid = ScorerInvalid("dummy-scorer-invalid")
scorer_out_of_range = ScorerOutOfRange("dummy-scorer-out-of-range")
scorer_leaks_answer = ScorerLeaksAnswer("dummy-scorer-leaks-answer")
