"""GET /policy: the loaded policy configuration, read-only (Phase 8 brief 1.2).

The "Demonstration assumptions" panel on the order-detail page is populated from here, so that no monetary
assumption, rate or threshold is ever written into the frontend. Every section and key of
`config/policy_v1_0.toml` is returned as the policy engine loaded it, with a server-formatted `Money` for
every `*_inr` value (§4: the UI never formats money). Internal key required, like every internal route.
"""
from dataclasses import fields

from fastapi import APIRouter, Depends

from sentinel.api.deps import verify_internal_key
from sentinel.api.schemas import PolicyAssumptionSection, PolicyAssumptionsResponse, PolicyAssumptionValue
from sentinel.money import make_money
from sentinel.policy.config import SECTIONS, load_policy_config

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])

MONEY_SUFFIX = "_inr"


@router.get("/policy", response_model=PolicyAssumptionsResponse)
def get_policy() -> PolicyAssumptionsResponse:
    cfg = load_policy_config()
    sections = []
    for name, cls in SECTIONS.items():                     # declaration order = the file's section order
        section = getattr(cfg, name)
        values = []
        for field in fields(cls):
            value = getattr(section, field.name)
            money = make_money(value) if field.name.endswith(MONEY_SUFFIX) else None
            values.append(PolicyAssumptionValue(key=field.name, value=value, money=money))
        sections.append(PolicyAssumptionSection(section=name, values=values))
    return PolicyAssumptionsResponse(policy_version=cfg.policy.version, policy_config_sha256=cfg.config_sha256,
                                     notice=cfg.policy.notice, sections=sections)
