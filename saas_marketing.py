"""
REZE SaaS 마케팅 — LemonSqueezy webhook + 이메일 자동화 + 크로스 프로모션.

역할:
- LemonSqueezy webhook 수신 (FastAPI 엔드포인트)
  → subscription_created → 온보딩 시퀀스
  → subscription_payment_failed → 결제 실패 알림
  → subscription_cancelled → 이탈 방지 이메일
- 블로그 글에 자동 SaaS CTA 삽입
- Product Hunt 런치 타이밍 제안

webhook 검증: X-Signature 헤더 (HMAC SHA-256)
SSOT: email_campaigns 테이블
FastAPI 라우트: /webhook/lemonsqueezy

★ 이메일 도구 미선택 → 추상 인터페이스 + Brevo 기본 구현
  나중에 Loops/Kit으로 교체 가능
"""

import json
import hmac
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
import aiohttp

import config

import logging
logger = logging.getLogger("REZE.saas_marketing")

router = APIRouter(prefix="/webhook", tags=["webhook"])


# === 이메일 추상 레이어 ===

class EmailProvider:
    """이메일 발송 추상 클래스. 구현체 교체 가능."""

    async def send(self, to_email: str, subject: str, html_body: str,
                   tags: list = None) -> bool:
        raise NotImplementedError


class BrevoProvider(EmailProvider):
    """Brevo (구 Sendinblue) — 무료 무제한 연락처, 300발송/일."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.brevo.com/v3"

    async def send(self, to_email: str, subject: str, html_body: str,
                   tags: list = None) -> bool:
        if not self.api_key:
            logger.warning("Brevo API key not set — email skipped")
            return False

        payload = {
            "sender": {"name": "RunState", "email": "noreply@runstate.dev"},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_body,
        }
        if tags:
            payload["tags"] = tags

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/smtp/email",
                    headers={"api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"Email sent to {to_email}: {subject}")
                        return True
                    else:
                        body = await resp.text()
                        logger.warning(f"Brevo {resp.status}: {body[:200]}")
                        return False
        except Exception as e:
            logger.error(f"Brevo send failed: {e}")
            return False


class NoopProvider(EmailProvider):
    """이메일 키 미설정 시 — 로그만 남기고 패스."""

    async def send(self, to_email: str, subject: str, html_body: str,
                   tags: list = None) -> bool:
        logger.info(f"[NOOP] Would email {to_email}: {subject}")
        return True


# === 이메일 시퀀스 템플릿 ===

ONBOARDING_SEQUENCE = [
    {
        "delay_hours": 0,
        "subject": "Welcome to {product_name}! 🎉",
        "body": """<h2>Welcome aboard!</h2>
<p>Thanks for subscribing to {product_name}.</p>
<p>Here's how to get started in 3 steps:</p>
<ol>
<li>Log in to your dashboard</li>
<li>Complete the quick setup wizard</li>
<li>Launch your first automation</li>
</ol>
<p>Questions? Just reply to this email.</p>
<p>— The RunState Team</p>""",
    },
    {
        "delay_hours": 48,
        "subject": "Quick tip: Get more from {product_name}",
        "body": """<h2>Pro tip #1</h2>
<p>Most successful users set up their first project within 48 hours.</p>
<p>Need help? Check our <a href="https://docs.runstate.dev">documentation</a>.</p>
<p>— The RunState Team</p>""",
    },
]

PAYMENT_FAILED_TEMPLATE = {
    "subject": "⚠️ Payment issue with your {product_name} subscription",
    "body": """<h2>Payment failed</h2>
<p>We couldn't process your latest payment for {product_name}.</p>
<p>Please update your payment method to continue using the service:</p>
<p><a href="{customer_portal_url}">Update Payment →</a></p>
<p>If you need help, just reply to this email.</p>
<p>— The RunState Team</p>""",
}

CANCELLATION_TEMPLATE = {
    "subject": "We're sorry to see you go — {product_name}",
    "body": """<h2>Your feedback matters</h2>
<p>We noticed you cancelled {product_name}.</p>
<p>Would you mind sharing what we could improve? Just reply to this email.</p>
<p>If you change your mind, you can reactivate anytime.</p>
<p>— The RunState Team</p>""",
}


class SaaSMarketing:
    """SaaS 마케팅 자동화 엔진."""

    def __init__(self, ssot, alert_fn=None):
        self.ssot = ssot
        self.alert_fn = alert_fn

        # 이메일 프로바이더 선택
        if config.EMAIL_PROVIDER == "brevo" and config.BREVO_API_KEY:
            self.email = BrevoProvider(config.BREVO_API_KEY)
        else:
            self.email = NoopProvider()
            if config.BREVO_API_KEY:
                logger.info("Email provider: Brevo")
            else:
                logger.info("Email provider: NOOP (no API key)")

    async def handle_webhook_event(self, event_name: str, data: dict) -> dict:
        """
        LemonSqueezy webhook 이벤트 처리.

        event_name: subscription_created, subscription_updated,
                    subscription_payment_failed, subscription_expired, order_created
        data: webhook payload의 data 객체
        """
        attrs = data.get("attributes", {})
        product_name = attrs.get("product_name", "Unknown")
        user_email = attrs.get("user_email", "")

        logger.info(f"Webhook: {event_name} — {product_name} — {user_email}")

        result = {"event": event_name, "handled": False}

        if event_name == "subscription_created":
            # 온보딩 시퀀스 시작
            for i, step in enumerate(ONBOARDING_SEQUENCE):
                subject = step["subject"].format(product_name=product_name)
                body = step["body"].format(product_name=product_name)

                # delay_hours=0만 즉시 발송, 나머지는 기록만
                if step["delay_hours"] == 0 and user_email:
                    sent = await self.email.send(user_email, subject, body, tags=["onboarding"])
                    campaign_id = self.ssot.save_email_campaign(
                        "onboarding", product_name, user_email, subject, event_name
                    )
                    if sent:
                        self.ssot.update_email_status(campaign_id, "sent")
                else:
                    # 지연 발송은 기록만 (스케줄러에서 처리)
                    self.ssot.save_email_campaign(
                        f"onboarding_step_{i}", product_name, user_email,
                        subject, f"{event_name}:delay_{step['delay_hours']}h"
                    )

            # Discord 알림
            if self.alert_fn:
                try:
                    await self.alert_fn(
                        "info", "saas_marketing",
                        f"🎉 새 구독: {product_name} — {user_email}"
                    )
                except Exception:
                    pass

            result["handled"] = True

        elif event_name == "subscription_payment_failed":
            portal_url = attrs.get("urls", {}).get("customer_portal", "#")
            subject = PAYMENT_FAILED_TEMPLATE["subject"].format(product_name=product_name)
            body = PAYMENT_FAILED_TEMPLATE["body"].format(
                product_name=product_name, customer_portal_url=portal_url
            )

            if user_email:
                sent = await self.email.send(user_email, subject, body, tags=["payment_failed"])
                campaign_id = self.ssot.save_email_campaign(
                    "payment_failed", product_name, user_email, subject, event_name
                )
                if sent:
                    self.ssot.update_email_status(campaign_id, "sent")

            if self.alert_fn:
                try:
                    await self.alert_fn(
                        "warning", "saas_marketing",
                        f"⚠️ 결제 실패: {product_name} — {user_email}"
                    )
                except Exception:
                    pass

            result["handled"] = True

        elif event_name in ("subscription_cancelled", "subscription_expired"):
            subject = CANCELLATION_TEMPLATE["subject"].format(product_name=product_name)
            body = CANCELLATION_TEMPLATE["body"].format(product_name=product_name)

            if user_email:
                sent = await self.email.send(user_email, subject, body, tags=["churn"])
                campaign_id = self.ssot.save_email_campaign(
                    "cancellation", product_name, user_email, subject, event_name
                )
                if sent:
                    self.ssot.update_email_status(campaign_id, "sent")

            if self.alert_fn:
                try:
                    await self.alert_fn(
                        "warning", "saas_marketing",
                        f"❌ 구독 취소: {product_name} — {user_email}"
                    )
                except Exception:
                    pass

            result["handled"] = True

        elif event_name == "order_created":
            # 단건 결제 → 감사 이메일
            if self.alert_fn:
                total = attrs.get("total_formatted", "$0")
                try:
                    await self.alert_fn(
                        "info", "saas_marketing",
                        f"💰 새 주문: {product_name} — {total} — {user_email}"
                    )
                except Exception:
                    pass
            result["handled"] = True

        # SSOT 기록
        self.ssot.save_signal(f"webhook_{event_name}", json.dumps({
            "product": product_name,
            "email": user_email[:3] + "***" if user_email else "",
            "handled": result["handled"],
        }))

        return result

    def generate_blog_cta(self, product_name: str, article_topic: str) -> str:
        """
        블로그 글 주제에 맞는 SaaS CTA HTML 생성.
        seo_optimizer.py와 연동하여 글 끝에 삽입.
        """
        cta_map = {
            "postpilot": {
                "headline": "Automate Your Blog with AI",
                "description": "PostPilot writes, optimizes, and publishes blog posts automatically.",
                "url": "https://postpilot.runstate.dev",
                "cta_text": "Start Free Trial →",
            },
            "browserpilot": {
                "headline": "Automate Any Browser Task",
                "description": "BrowserPilot handles repetitive web tasks so you don't have to.",
                "url": "https://browserpilot.runstate.dev",
                "cta_text": "Try BrowserPilot →",
            },
            "quotepilot": {
                "headline": "AI-Powered Catering Quotes",
                "description": "Generate professional catering quotes in seconds.",
                "url": "https://quotepilot.runstate.dev",
                "cta_text": "Get Started →",
            },
        }

        product = cta_map.get(product_name.lower(), cta_map.get("postpilot"))
        return f"""
<div style="background:#f8f9fa;border:1px solid #e9ecef;border-radius:8px;padding:24px;margin:32px 0;text-align:center;">
  <h3 style="margin:0 0 8px 0;">{product['headline']}</h3>
  <p style="color:#6c757d;margin:0 0 16px 0;">{product['description']}</p>
  <a href="{product['url']}" style="background:#6366f1;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">
    {product['cta_text']}
  </a>
</div>"""


# === Singleton (daemon에서 초기화) ===
_marketing_instance: Optional[SaaSMarketing] = None


def get_marketing() -> Optional[SaaSMarketing]:
    return _marketing_instance


def init_marketing(ssot, alert_fn=None):
    global _marketing_instance
    _marketing_instance = SaaSMarketing(ssot, alert_fn)
    return _marketing_instance


# === FastAPI Webhook 엔드포인트 ===

def _verify_ls_signature(body: bytes, signature: str) -> bool:
    """LemonSqueezy HMAC SHA-256 서명 검증."""
    secret = config.LEMONSQUEEZY_WEBHOOK_SECRET
    if not secret:
        logger.warning("LemonSqueezy webhook secret not set — skipping verification")
        return True  # secret 미설정 시 통과 (개발 모드)

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    """
    LemonSqueezy webhook 수신 엔드포인트.
    POST /webhook/lemonsqueezy

    Headers:
      X-Signature: HMAC SHA-256 해시
    Body:
      {"meta": {"event_name": "..."}, "data": {...}}
    """
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_ls_signature(body, signature):
        logger.warning("Invalid LemonSqueezy webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_name = payload.get("meta", {}).get("event_name", "unknown")
    data = payload.get("data", {})

    marketing = get_marketing()
    if not marketing:
        logger.error("SaaSMarketing not initialized")
        return {"status": "error", "message": "Marketing module not ready"}

    result = await marketing.handle_webhook_event(event_name, data)
    return {"status": "ok", "event": event_name, "handled": result.get("handled", False)}
