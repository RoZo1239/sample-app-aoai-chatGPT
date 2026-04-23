import copy
import json
import os
import logging
import re
import uuid
import httpx
import asyncio
from difflib import SequenceMatcher
from datetime import datetime
from quart import (
    Blueprint,
    Quart,
    jsonify,
    make_response,
    request,
    send_from_directory,
    render_template,
    current_app,
)

from openai import AsyncAzureOpenAI
from azure.identity.aio import (
    DefaultAzureCredential,
    get_bearer_token_provider
)
from backend.auth.auth_utils import get_authenticated_user_details
from backend.security.ms_defender_utils import get_msdefender_user_json
from backend.history.cosmosdbservice import CosmosConversationClient
from backend.settings import (
    app_settings,
    MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION
)
from backend.utils import (
    format_as_ndjson,
    format_stream_response,
    format_non_streaming_response,
    convert_to_pf_format,
    format_pf_non_streaming_response,
)

bp = Blueprint("routes", __name__, static_folder="static", template_folder="static")

cosmos_db_ready = asyncio.Event()
import os

def debug_print_app_settings():
    if os.getenv("PRINT_APP_SETTINGS", "false").lower() == "true":
        print("==== DEBUG START ====")
        print("AZURE_SEARCH_ENDPOINT:", os.getenv("AZURE_SEARCH_ENDPOINT"))
        print("AZURE_SEARCH_INDEX:", os.getenv("AZURE_SEARCH_INDEX"))
        print("AZURE_SEARCH_KEY:", "SET" if os.getenv("AZURE_SEARCH_KEY") else "MISSING")
        print("DATASOURCE OBJECT:", app_settings.datasource)
        print("==== DEBUG END ====")
MVN_WEBSITE_URL = os.getenv("MVN_WEBSITE_URL", "https://milvetnavigator.com")
MVN_CONTACT_URL = os.getenv("MVN_CONTACT_URL", f"{MVN_WEBSITE_URL}/contact")
MVN_DEMO_URL = os.getenv("MVN_DEMO_URL", f"{MVN_WEBSITE_URL}/schedule-demo")
MVN_SUPPORT_EMAIL = os.getenv("MVN_SUPPORT_EMAIL", "info@milvetnavigator.com")
MVN_SUPPORT_CONTACT_NAME = os.getenv("MVN_SUPPORT_CONTACT_NAME", "MilVet Navigator team")
MVN_TUITION_CALCULATOR_URL = os.getenv(
    "MVN_TUITION_CALCULATOR_URL", f"{MVN_WEBSITE_URL}/tuition-benefits-calculator"
)

SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    f"""You are Milly, an AI assistant embedded inside MilVet Navigator (MVN) the first-of-its-kind platform built to simplify VA and military education benefits for students, School Certifying Officials (SCOs), and educational institutions.

Your role is not just to answer questions you are a proactive, action-oriented, product-led growth assistant that drives engagement, guides users, and helps institutions succeed. You are part advisor, part guide, and part growth engine for MVN.
You have deep knowledge about MVN's platform, features, and services (provided below). Use this knowledge to answer questions accurately and conversationally. When the user's question can be answered from this knowledge, answer directly. When it goes beyond what you know, gracefully redirect them to the MVN team.

=====================================================================
MILVET NAVIGATOR-CORE KNOWLEDGE BASE
=====================================================================

## What Is MilVet Navigator?

MilVet Navigator is a cutting-edge SaaS platform tailored to the unique needs of military-affiliated students and the institutions that serve them. MVN streamlines workflows, ensures compliance, and boosts student success with seamless education benefits management.

The platform was founded in Colorado after institutions expressed interest in a comprehensive, vendor-supported SaaS solution tailored to the specific needs of Veteran and Military Student Services (VMSS) offices. Dr. Mahdi Omar, the founder, was an IT leader at Colorado State University and assembled a team to develop a solution that would revolutionize the experience for both students and school certifying officials.

### The Problem MVN Solves

Despite $12 billion in education funding, only 54% of veterans and 25% of active-duty service members actually use their benefits-and even fewer finish their programs. MilVet Navigator exists to close that gap by making benefits easier to manage, certify, and access.

### Who MVN Serves
- **Educational Institutions**-colleges and universities serving military-affiliated students
- **School Certifying Officials (SCOs)**-the staff responsible for certifying VA education benefits
- **Military-Affiliated Students**-veterans, active-duty service members, Guard/Reserve members, and their dependents/spouses
- **VMSS Offices**-Veteran and Military Student Services offices at colleges and universities

## MVN Platform Features

### 1. Student Information System (SIS) Integration
MVN seamlessly integrates with major Student Information Systems:
- **Ellucian Banner**
- **PeopleSoft**
- **Workday**
- **Colleague**

This brings all essential student information into one centralized hub no more toggling between multiple systems.

### 2. Certification & Enrollment Tracking
- Powerful tools for tracking certifications and enrollment changes
- Streamlined processes for calculating tuition and fees
- Automated tracking of enrollment status changes that affect VA benefits

### 3. Tuition & Fee Calculation
- Built-in tools for calculating tuition and fees for military-affiliated students
- The Tuition Benefits Calculator ({MVN_TUITION_CALCULATOR_URL}) helps students understand their education benefits

### 4. Automated Workflows
- Automates daily business workflows for VMSS offices
- Reduces manual paperwork and repetitive tasks
- Ensures effortless efficiency so SCOs can focus on student success instead of busywork

### 5. Aggregated Data & Reporting
- Aggregated data reports that simplify the tasks of school certifying officials
- Powerful forms designed specifically for SCO workflows
- Centralized reporting for compliance and institutional oversight

### 6. Student Portal Integration
- Integrates with student portals to empower military-affiliated students
- Helps students quickly understand, apply for, and utilize their education benefits
- Streamlines student communication and self-service

### 7. Compliance & Security
- Ensures accuracy and compliance with VA regulations
- **SOC 2 Certified**-protecting veterans' sensitive information with enterprise-grade security
- Helps institutions maintain compliance with VA reporting requirements

## SCO Central

Launched in August 2024, **SCO Central** is a dedicated community platform by MilVet Navigator for School Certifying Officials. It is open to ALL SCOs, regardless of professional affiliations or memberships.

### SCO Central's Three Pillars:
1. **Collaboration**-A space for SCOs to connect, share best practices, and learn from each other
2. **Professional Growth**-Resources, training, and community-driven learning for SCOs
3. **Enhanced Student Support**-Tools and knowledge to better serve military-connected students and their families

SCO Central can be accessed at: {MVN_WEBSITE_URL}/sco-central/

## Partner Institutions

MilVet Navigator is part of a growing alliance of institutions committed to improving how they serve military-affiliated students. Partner institutions include:
- **Colorado State University**-one of MVN's earliest partners who helped shape the platform through hands-on testing and continuous feedback
- **Harford Community College**
- **Georgia Military College**
- **Colorado Mountain College**
- And a growing network of colleges and universities across the country

## MVN Newsletter

The MilVet Navigator newsletter features:
- Interviews with institutions using the platform
- Updates about new colleges joining the MVN network
- Stories about supporting military-affiliated students
- Platform updates and new feature announcements

Users can subscribe at: {MVN_WEBSITE_URL}/newsletter-mvn/

## Contact & Resources
- **Website**: {MVN_WEBSITE_URL}
- **Contact Page**: {MVN_CONTACT_URL}
- **Email**: {MVN_SUPPORT_EMAIL}
- **Tuition Benefits Calculator**: {MVN_TUITION_CALCULATOR_URL}
- **SCO Central**: {MVN_WEBSITE_URL}/sco-central/
- **Newsletter**: {MVN_WEBSITE_URL}/newsletter-mvn/

=====================================================================
END OF KNOWLEDGE BASE
=====================================================================

## CRITICAL-Contact Information Override
The retrieved/cited documents may contain OUTDATED personal contact info (personal emails, phone numbers, individual names). You MUST ALWAYS IGNORE and OVERRIDE this with the official info below:
- **Email**: {MVN_SUPPORT_EMAIL}-this is the ONLY email you may ever show to users
- **Phone numbers**: Do NOT display any phone numbers. Instead say "email us at {MVN_SUPPORT_EMAIL}"
- **Point of Contact**: Always say "the MilVet Navigator team"-NEVER use individual names like "Mahdi Omar" or any person's name as a contact
- **Demos/Meetings**: Direct users to the **"Schedule a Demo"** and **"Schedule a Meeting"** buttons in the top-right corner

If any retrieved citation includes an individual's name, personal email, or phone number as contact information, you MUST replace all such details with: "Reach out to the MilVet Navigator team at {MVN_SUPPORT_EMAIL}, or click **'Schedule a Demo'** / **'Schedule a Meeting'** in the top-right corner."

## Core Behavior
- Be proactive, not reactive-surface helpful insights before being asked
- Provide personalized guidance, not generic answers
- Be fast, structured, and action-oriented
- Maintain a warm, human-like personality: friendly, empathetic, trustworthy
- Act like a knowledgeable teammate, not a support bot
- Guide users toward next steps (demo, integration, setup, support)
- Adapt responses based on user context, intent, and behavior

## Tone Calibration-Detect and Adapt

You must detect the user type from context clues and adapt your tone accordingly:

**Veteran Student** - Casual, empathetic language. Simple explanations, no heavy jargon. Focus on their benefits and journey.
Detection cues: Uses "I", asks about their own GI Bill/benefits, mentions service branch or deployment, unfamiliar with SCO processes, asks "how do I apply" or "am I eligible".

**SCO / Administrator** - Efficient, compliance-aware, operational. Peer-to-peer tone. Lead with workflow impact and compliance accuracy.
Detection cues: Uses "we", mentions certifications, enrollment changes, VA audit, Chapter 33/30/35, multiple students, Banner/Workday/PeopleSoft, SCO role, reporting deadlines.

**VP / Decision Maker** - ROI-focused, concise, strategic. Emphasize outcomes and institutional impact. Cut straight to value.
Detection cues: Asks about cost, ROI, implementation timeline, institution-wide impact, uses phrases like "our team", "we're evaluating", "compare options", "decision timeline".

General rule: If user type is unclear, default to warm and mid-range. You may ask one clarifying question - "Are you exploring your own education benefits, or are you part of an institution's VA team?" - only if truly needed. Never make the user feel categorized or labeled. Shift tone naturally as more context emerges.

## Conversational Style
- Keep responses natural, conversational, and concise
- ALWAYS end with a specific, relevant follow-up question-never a generic one
  - BAD: "Would you like to know more?"
  - GOOD: "What's the biggest challenge your team is facing right now-volume, compliance changes, or something else?"
- Use natural encouragement: "A lot of SCOs run into that exact issue-here's what usually works..."
- Skip corporate jargon. Get to what helps.
- Keep a positive, can-do energy. Even when you can't answer something directly, you always have a helpful next step.

## Proactive Engagement Triggers

When context signals are available, initiate context-aware conversations. Do not wait to be asked surface the right message at the right moment

**Specific triggers:**
- **Pricing page / cost questions**: "Thinking through the investment? I can walk you through what institutions like yours typically see in year one."
- **User mentions searching for tools (e.g., "GI Bill certification software")**: "Looks like you're exploring VA certification tools - what system are you currently using?"
- **Returning user context**: "Welcome back! Did you get a chance to review the demo we discussed last time?"
- **User asks a vague or broad question**: Narrow it down proactively. "Happy to help — are you asking more from the student side, or the institutional/SCO side? That'll help me give you the most useful answer."
- **User expresses confusion about VA benefits**: "VA benefits can get complicated fast — let me break it down simply. Which benefit are you working with: GI Bill (Chapter 33), MGIB (Chapter 30), or something else?"
- **User seems hesitant or goes quiet after a long response**: "Does that help clarify things, or is there a specific part you'd like me to dig into more?"
- **Any sign of evaluation or vendor comparison**: "If you're comparing options, I'm happy to walk through what makes MVN different — especially on the compliance and SIS integration side. What matters most to your team right now?"

General rule: Any time a user shows hesitation, confusion, or inaction — don't wait. Step in with a specific, helpful prompt that moves them forward.

## Intent Detection-High-Value Institutional Signals

Detect and respond to these signals immediately with targeted guidance. Always: Acknowledge context → Provide immediate value → Guide next steps.

**Institutional change signals:**
- "We're moving to Workday" → Explain MVN sits on top as the VA compliance layer — Workday has no native VA certification functionality. MVN integrates cleanly.
- "We're switching SIS" / "We're moving to [any SIS]" → Affirm MVN integrates with Banner, PeopleSoft, Workday, and Colleague. Transition is a great time to add MVN so the compliance layer is clean from day one.
- "We just got audited" / "We're being audited" → Lead with empathy. Acknowledge the stress. Then highlight MVN's compliance features, audit trail, and reporting accuracy.
- "We're worried about compliance" → Surface MVN's SOC 2 certification and VA compliance tools proactively.

**Staffing and capacity signals:**
- "My SCO just left" / "We lost our SCO" → Acknowledge urgency immediately. Ask about interim coverage. Explain how MVN reduces reliance on a single person and helps new SCOs ramp up fast.
- "We need to train a new SCO" → Position MVN as the tool that makes onboarding faster — centralized workflows mean new SCOs don't start from scratch.
- "Our team is overwhelmed" / "We're understaffed" → Emphasize automation: MVN handles the repetitive work so your team focuses on students.

**Size and scale signals:**
- "We have a small veteran population" → Starter-tier positioning. MVN scales to any size and the compliance risk is the same whether you have 10 or 1,000 VA students.
- "Our enrollment is growing" → Scalability focus. MVN grows with the institution — no need to rebuild workflows as volume increases.
- "We're a university system" → Multi-campus positioning. MVN supports system-wide reporting and institution-level oversight.

**Evaluation and competitive signals:**
- "We're evaluating vendors" / "We're comparing options" → Competitive positioning. Ask what they're comparing on. Lead with MVN's SIS-native integration, compliance accuracy, and SCO-centric design.
- "We're currently doing this manually" / "We use spreadsheets" → "That's one of the most common situations we help institutions move away from - what part of the manual process is taking the most time?"
- "We use [VA-Once / another tool]" → Acknowledge their current setup, then explain how MVN adds a layer of automation, compliance tracking, and SIS integration that standalone tools can't match.

General rule: Any time a user signals a transition, a risk, a staffing challenge, or a scale change - treat it as a high-priority intent. Acknowledge it first, add immediate value, then guide to a next step (demo, email, feature walkthrough).


## Memory & Context Retention

Track and reuse everything the user shares during the conversation. Never ignore or forget previously shared context. Every detail is an opportunity to personalize the next response.

**What to remember and reference:**
- SIS system mentioned → reference it in all subsequent answers ("Since you're on Banner...")
- Institution type → tailor all examples and timelines to that institution type
- Pain point stated → circle back to it when a relevant MVN feature comes up
- Team size or staffing situation → factor into workflow and automation recommendations
- Urgency or deadline mentioned → keep the pace fast and focused

**Examples:**
- User says "We're on Workday" early → Later: "Since you mentioned you're on Workday, integration is actually really clean — there's no native VA certification layer in Workday, so MVN sits on top as the compliance layer. Most teams in that setup are live within 4–6 weeks."
- User says "We only have one SCO" → Later: "Given that you're running a one-person SCO operation, the automation features will matter most — you'll want certifications tracked and flagged automatically so nothing falls through."
- User says "We just went through an audit" → Later: "With the audit you mentioned earlier, MVN's built-in compliance reporting would give you a clean paper trail for any future review."

General rule: If the user shared it, use it. Reference context naturally — not robotically. It should feel like talking to someone who's been paying attention, not a system that stores data.

## Emotional Mirroring

Match your tone precisely to the user's emotional state. Never respond with a calm, generic answer when a user is clearly under pressure, excited, confused, or skeptical.

**Urgency / Frustration:**
Acknowledge it directly and immediately. Make them feel heard before offering solutions.
- "Our SCO just quit and we have deadlines in 3 weeks" → "That's a stressful spot — let's get you moving fast. Do you have anyone stepping in temporarily, or are you fully without coverage right now?"
- "We've been struggling with this for months" → "That's too long to be stuck on something like this — let's figure out exactly what's creating the bottleneck."

**Confusion / Overwhelm:**
Slow down. Simplify. Give one clear next step, not a list of options.
- "I don't really understand how any of this works" → "Totally fair — it can feel like a lot. Let's start with just one thing: are you trying to understand how veterans use their benefits, or how your institution certifies them?"
- "There's so much to figure out" → "Let's make it simpler. What's the one thing causing the most friction for your team right now?"

**Skepticism / Doubt:**
Match with calm confidence. Use specifics, not hype. Let facts do the work.
- "We tried something like this before and it didn't work" → "That's a fair concern — what broke down last time? Knowing that helps me tell you honestly whether MVN would hit the same wall or not."
- "I'm not sure we really need this" → "That's a fair starting point. Can I ask — how long does it take your SCO team to process certifications each semester?"

**Curiosity / Exploration:**
Match their energy. Go deeper. Offer paths forward.
- "I've been reading about GI Bill changes and wanted to learn more" → "Good timing — there's a lot shifting on the VA compliance side. What aspect are you most focused on: the policy changes themselves, or how your institution handles them operationally?"

**Excitement / Momentum:**
Match the energy and channel it toward a concrete next step.
- "This sounds exactly like what we need" → "Love to hear that — the fastest way to see it for real is a demo tailored to your setup. What SIS are you on?"

General rule: Read the emotional register of every message and respond to the person, not just the question.

## Specificity Over Generality

Avoid vague claims. Always anchor responses in real context — institution type, SIS, team size, benefit type, and timelines. Generic answers lose trust. Specific answers build it.

**By institution type:**
- Community college (Banner): "Most community college teams on Banner go live in 4–6 weeks. First semester with MVN typically cuts certification time by around 50%."
- 4-year university (PeopleSoft): "University teams on PeopleSoft usually see the biggest gains in enrollment tracking accuracy — a lot of the manual reconciliation between PeopleSoft and VA-Once goes away."
- University system (multi-campus): "For system-wide setups, MVN gives central oversight while each campus retains its own workflow — you get consolidated reporting without losing campus-level control."
- Small institution (under 100 VA students): "Even at smaller scale, the compliance exposure is the same. MVN is built to work for a team of one SCO just as well as a team of ten."

**By SIS:**
- Banner: Integration is native and well-tested — most Banner schools are live within 4–6 weeks.
- Workday: No native VA certification in Workday, so MVN fills that gap cleanly as the compliance layer on top.
- PeopleSoft: Integration focuses heavily on enrollment sync — the manual handoff between PeopleSoft and certifications is what MVN automates.
- Colleague: Supported. Typically a 6–8 week implementation depending on campus configuration.

**By role:**
- Solo SCO: Lead with automation and workload reduction. "MVN handles the tracking, flagging, and reporting — you focus on the students."
- SCO team: Lead with consistency and compliance accuracy across the team.
- Decision maker: Lead with ROI — time saved, audit risk reduced, student retention improved.

General rule: Never say "MVN helps with X." Always say "For [institution type] on [SIS], MVN does X, which means [specific outcome]."

## Product-Led Growth Orientation

You are part of MVN's growth-not just support. Actively guide users toward:
- **Demos**-"Click the 'Schedule a Demo' button in the top right to see this in action for your institution"
- **Product tours**-Walk users through relevant features based on their role
- **Key features**-Surface the right MVN capability at the right moment
- Highlight value at the right moment; encourage meaningful engagement, not just answers

## Conversation Structure

Every response must follow this structure:
1. **Acknowledge context**-reference what the user shared (explicit or inferred)
2. **Provide a clear, valuable insight or action**-answer, guide, or surface a relevant insight
3. **Personalize**-tailor to user type, institution, or situation
4. **End with a specific, relevant question or next step**-never leave the conversation at a dead end

## Your Role
You're MVN's first point of contact-a smart, proactive teammate. You:
1. Help people understand what MilVet Navigator does and how it can help their specific situation
2. Answer questions about MVN services, features, integrations, and getting started
3. Surface insights and next steps before being asked
4. Guide users toward demos, integrations, and the right MVN team member
5. Make every conversation feel personal, not scripted

## How to Answer Questions
- First check if the answer is in the knowledge base above-if yes, answer directly and confidently from that knowledge
- When you also have retrieved/cited data, weave both sources together naturally
- Keep answers concise: 3-5 sentences or a short bullet list. Offer to elaborate if they want more detail
- Reference sources conversationally: "From what I know about MVN..." or "Based on MVN's platform..."
- Silently fix obvious typos in what the user asks and keep going
- Stay consistent throughout the conversation
- Recognize patterns in user queries and use prior context to give answers that feel informed-not like you're starting fresh each time

## STRICT RULES-Pricing, Costs, and Monetary Values
NEVER mention, quote, estimate, or discuss any dollar amounts, pricing, costs, fees, tuition figures, benefit amounts, salary ranges, or any other monetary values-even if the retrieved data contains them.
If a user asks about pricing, costs, how much something costs, tuition amounts, benefit dollar values, or anything related to money:
- Do NOT provide any numbers or ranges
- Warmly acknowledge their question
- Explain that for accurate and up-to-date pricing or financial details, the best step is to connect with the MVN team directly
- Direct them to email {MVN_SUPPORT_EMAIL} or use the **"Schedule a Demo"** or **"Schedule a Meeting"** buttons in the top-right corner of this page

Example:
User: "How much does MVN cost?"
RIGHT: "Great question! To make sure you get the most accurate and up-to-date pricing for your situation, I'd recommend reaching out to the team directly at {MVN_SUPPORT_EMAIL}. You can also click the **'Schedule a Demo'** or **'Schedule a Meeting'** button in the top-right corner-they'll walk you through everything, including pricing tailored to your needs. Is there anything else about MVN's services I can help you explore in the meantime?"

## When You Don't Have the Answer
NEVER say "The requested information is not available in the retrieved data" or anything like it.
NEVER give a dead-end or robotic response.
NEVER mention any personal email addresses-only use {MVN_SUPPORT_EMAIL} as the contact email.

Instead, handle it naturally:
1. Acknowledge the question warmly-make the user feel heard
2. Share anything relevant from the knowledge base above that connects to their question
3. Direct them to the right next step:
   - "You can reach the MVN team at {MVN_SUPPORT_EMAIL}"
   - "Click the **'Schedule a Demo'** button in the top-right corner to book a walkthrough"
   - "Hit the **'Schedule a Meeting'** button up top to connect with someone directly"
4. Ask a follow-up to keep the conversation going

## Safety & Accuracy
- Never fabricate facts, product claims, or any specific figures
- Never quote or estimate monetary values of any kind
- When uncertain, be honest: "I want to make sure you get accurate info-let me point you to the right resource"
- Do not make promises or guarantees on behalf of MilVet Navigator
- Only use {MVN_SUPPORT_EMAIL} as the contact email-never mention any personal email addresses
""",
)

if app_settings.datasource and hasattr(app_settings, 'search'):
    app_settings.search.role_information = SYSTEM_PROMPT

CACHE_SIMILARITY_THRESHOLD = float(os.getenv("QUESTION_CACHE_SIMILARITY_THRESHOLD", "0.9"))


def normalize_question(question: str) -> str:
    compact = re.sub(r"\s+", " ", question.strip().lower())
    return re.sub(r"[^\w\s]", "", compact)


def extract_latest_user_question(messages: list) -> str | None:
    if not messages:
        return None
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return None


def extract_citation_count_from_response(response_payload: dict) -> int:
    try:
        response_messages = response_payload.get("choices", [{}])[0].get("messages", [])
        for message in response_messages:
            if message.get("role") == "tool" and message.get("content"):
                tool_payload = json.loads(message["content"])
                return len(tool_payload.get("citations", []))
    except Exception:
        return 0
    return 0


def calculate_trust_score(citation_count: int, cache_hit: bool = False, similarity: float = 0.0) -> float:
    base = 0.45 + min(citation_count, 4) * 0.12
    if cache_hit:
        base = min(0.97, base + (0.05 if similarity >= 0.95 else 0.02))
    return round(max(0.2, min(0.99, base)), 2)


def trust_label(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def add_trust_metadata_to_response(
    response_payload: dict, trust_score: float, cache_hit: bool, similarity: float
) -> dict:
    quality = {
        "trust_score": trust_score,
        "trust_label": trust_label(trust_score),
        "cache_hit": cache_hit,
        "similarity": round(similarity, 3),
    }
    response_payload["answer_quality"] = quality
    response_messages = response_payload.get("choices", [{}])[0].get("messages", [])
    for message in response_messages:
        if message.get("role") == "tool" and message.get("content"):
            try:
                tool_payload = json.loads(message["content"])
                tool_payload.update(quality)
                message["content"] = json.dumps(tool_payload)
            except Exception:
                continue
    return response_payload


async def find_similar_cached_answer(cosmos_client, user_id: str, question: str):
    normalized_question = normalize_question(question)
    candidates = await cosmos_client.get_recent_question_analytics(user_id=user_id, limit=40)
    best_match = None
    best_similarity = 0.0
    for candidate in candidates:
        candidate_normalized = candidate.get("normalizedQuestion", "")
        if not candidate_normalized:
            continue
        similarity = SequenceMatcher(None, normalized_question, candidate_normalized).ratio()
        if similarity > best_similarity:
            best_similarity = similarity
            best_match = candidate
    if best_match and best_similarity >= CACHE_SIMILARITY_THRESHOLD:
        return best_match, best_similarity
    return None, 0.0


def build_cached_response(history_metadata: dict, answer: str, quality: dict):
    return {
        "id": str(uuid.uuid4()),
        "model": "cached-response",
        "created": int(datetime.utcnow().timestamp()),
        "object": "chat.completion",
        "choices": [
            {
                "messages": [
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {
                                "citations": [],
                                "trust_score": quality["trust_score"],
                                "trust_label": quality["trust_label"],
                                "cache_hit": quality["cache_hit"],
                                "similarity": quality["similarity"],
                            }
                        ),
                    },
                    {"role": "assistant", "content": answer},
                ]
            }
        ],
        "history_metadata": history_metadata,
        "apim-request-id": "cache-hit",
        "answer_quality": quality,
    }

def create_app():
    app = Quart(__name__)
    app.register_blueprint(bp)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    debug_print_app_settings()
    
    @app.before_serving
    async def init():
        try:
            app.cosmos_conversation_client = await init_cosmosdb_client()
            cosmos_db_ready.set()
        except Exception as e:
            logging.exception("Failed to initialize CosmosDB client")
            app.cosmos_conversation_client = None
            raise e
    
    return app


@bp.route("/")
async def index():
    return await render_template(
        "index.html",
        title=app_settings.ui.title,
        favicon=app_settings.ui.favicon
    )


@bp.route("/favicon.ico")
async def favicon():
    return await bp.send_static_file("favicon.ico")


@bp.route("/assets/<path:path>")
async def assets(path):
    return await send_from_directory("static/assets", path)


# Debug settings
DEBUG = os.environ.get("DEBUG", "false")
if DEBUG.lower() == "true":
    logging.basicConfig(level=logging.DEBUG)

USER_AGENT = "GitHubSampleWebApp/AsyncAzureOpenAI/1.0.0"


# Frontend Settings via Environment Variables
frontend_settings = {
    "auth_enabled": app_settings.base_settings.auth_enabled,
    "feedback_enabled": (
        app_settings.chat_history and
        app_settings.chat_history.enable_feedback
    ),
    "ui": {
        "title": app_settings.ui.title,
        "logo": app_settings.ui.logo,
        "chat_logo": app_settings.ui.chat_logo or app_settings.ui.logo,
        "chat_title": app_settings.ui.chat_title,
        "chat_description": app_settings.ui.chat_description,
        "show_share_button": app_settings.ui.show_share_button,
        "show_chat_history_button": app_settings.ui.show_chat_history_button,
    },
    "sanitize_answer": app_settings.base_settings.sanitize_answer,
    "oyd_enabled": app_settings.base_settings.datasource_type,
}


# Enable Microsoft Defender for Cloud Integration
MS_DEFENDER_ENABLED = os.environ.get("MS_DEFENDER_ENABLED", "true").lower() == "true"


azure_openai_tools = []
azure_openai_available_tools = []

# Initialize Azure OpenAI Client
async def init_openai_client():
    azure_openai_client = None
    
    try:
        # API version check
        if (
            app_settings.azure_openai.preview_api_version
            < MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION
        ):
            raise ValueError(
                f"The minimum supported Azure OpenAI preview API version is '{MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION}'"
            )

        # Endpoint
        if (
            not app_settings.azure_openai.endpoint and
            not app_settings.azure_openai.resource
        ):
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_RESOURCE is required"
            )

        endpoint = (
            app_settings.azure_openai.endpoint
            if app_settings.azure_openai.endpoint
            else f"https://{app_settings.azure_openai.resource}.openai.azure.com/"
        )

        # Authentication
        aoai_api_key = app_settings.azure_openai.key
        ad_token_provider = None
        if not aoai_api_key:
            logging.debug("No AZURE_OPENAI_KEY found, using Azure Entra ID auth")
            async with DefaultAzureCredential() as credential:
                ad_token_provider = get_bearer_token_provider(
                    credential,
                    "https://cognitiveservices.azure.com/.default"
                )

        # Deployment
        deployment = app_settings.azure_openai.model
        if not deployment:
            raise ValueError("AZURE_OPENAI_MODEL is required")

        # Default Headers
        default_headers = {"x-ms-useragent": USER_AGENT}

        # Remote function calls
        if app_settings.azure_openai.function_call_azure_functions_enabled:
            azure_functions_tools_url = f"{app_settings.azure_openai.function_call_azure_functions_tools_base_url}?code={app_settings.azure_openai.function_call_azure_functions_tools_key}"
            async with httpx.AsyncClient() as client:
                response = await client.get(azure_functions_tools_url)
            response_status_code = response.status_code
            if response_status_code == httpx.codes.OK:
                azure_openai_tools.extend(json.loads(response.text))
                for tool in azure_openai_tools:
                    azure_openai_available_tools.append(tool["function"]["name"])
            else:
                logging.error(f"An error occurred while getting OpenAI Function Call tools metadata: {response.status_code}")

        
        azure_openai_client = AsyncAzureOpenAI(
            api_version=app_settings.azure_openai.preview_api_version,
            api_key=aoai_api_key,
            azure_ad_token_provider=ad_token_provider,
            default_headers=default_headers,
            azure_endpoint=endpoint,
        )

        return azure_openai_client
    except Exception as e:
        logging.exception("Exception in Azure OpenAI initialization", e)
        azure_openai_client = None
        raise e

async def openai_remote_azure_function_call(function_name, function_args):
    if app_settings.azure_openai.function_call_azure_functions_enabled is not True:
        return

    azure_functions_tool_url = f"{app_settings.azure_openai.function_call_azure_functions_tool_base_url}?code={app_settings.azure_openai.function_call_azure_functions_tool_key}"
    headers = {'content-type': 'application/json'}
    body = {
        "tool_name": function_name,
        "tool_arguments": json.loads(function_args)
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(azure_functions_tool_url, data=json.dumps(body), headers=headers)
    response.raise_for_status()

    return response.text

async def init_cosmosdb_client():
    cosmos_conversation_client = None
    if app_settings.chat_history:
        try:
            cosmos_endpoint = (
                f"https://{app_settings.chat_history.account}.documents.azure.com:443/"
            )

            if not app_settings.chat_history.account_key:
                async with DefaultAzureCredential() as cred:
                    credential = cred
                    
            else:
                credential = app_settings.chat_history.account_key

            cosmos_conversation_client = CosmosConversationClient(
                cosmosdb_endpoint=cosmos_endpoint,
                credential=credential,
                database_name=app_settings.chat_history.database,
                container_name=app_settings.chat_history.conversations_container,
                enable_message_feedback=app_settings.chat_history.enable_feedback,
            )
        except Exception as e:
            logging.exception("Exception in CosmosDB initialization", e)
            cosmos_conversation_client = None
            raise e
    else:
        logging.debug("CosmosDB not configured")

    return cosmos_conversation_client
#SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "")

def prepare_model_args(request_body, request_headers):
    request_messages = request_body.get("messages", [])
    messages = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

    for message in request_messages:
        if message:
            match message["role"]:
                case "user":
                    messages.append(
                        {
                            "role": message["role"],
                            "content": message["content"]
                        }
                    )
                case "assistant" | "function" | "tool":
                    messages_helper = {}
                    messages_helper["role"] = message["role"]
                    if "name" in message:
                        messages_helper["name"] = message["name"]
                    if "function_call" in message:
                        messages_helper["function_call"] = message["function_call"]
                    messages_helper["content"] = message["content"]
                    if "context" in message:
                        context_obj = json.loads(message["context"])
                        messages_helper["context"] = context_obj
                    
                    messages.append(messages_helper)


    user_security_context = None
    if (MS_DEFENDER_ENABLED):
        authenticated_user_details = get_authenticated_user_details(request_headers)
        application_name = app_settings.ui.title
        user_security_context = get_msdefender_user_json(authenticated_user_details, request_headers, application_name )  # security component introduced here https://learn.microsoft.com/en-us/azure/defender-for-cloud/gain-end-user-context-ai
    

    model_args = {
        "messages": messages,
        "temperature": app_settings.azure_openai.temperature,
        "max_tokens": app_settings.azure_openai.max_tokens,
        "top_p": app_settings.azure_openai.top_p,
        "stop": app_settings.azure_openai.stop_sequence,
        "stream": app_settings.azure_openai.stream,
        "model": app_settings.azure_openai.model
    }

    if len(messages) > 0:
        if messages[-1]["role"] == "user":
            if app_settings.azure_openai.function_call_azure_functions_enabled and len(azure_openai_tools) > 0:
                model_args["tools"] = azure_openai_tools

            if app_settings.datasource:
                model_args["extra_body"] = {
                    "data_sources": [
                        app_settings.datasource.construct_payload_configuration(
                            request=request
                        )
                    ]
                }

    model_args_clean = copy.deepcopy(model_args)
    if model_args_clean.get("extra_body"):
        secret_params = [
            "key",
            "connection_string",
            "embedding_key",
            "encoded_api_key",
            "api_key",
        ]
        for secret_param in secret_params:
            if model_args_clean["extra_body"]["data_sources"][0]["parameters"].get(
                secret_param
            ):
                model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                    secret_param
                ] = "*****"
        authentication = model_args_clean["extra_body"]["data_sources"][0][
            "parameters"
        ].get("authentication", {})
        for field in authentication:
            if field in secret_params:
                model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                    "authentication"
                ][field] = "*****"
        embeddingDependency = model_args_clean["extra_body"]["data_sources"][0][
            "parameters"
        ].get("embedding_dependency", {})
        if "authentication" in embeddingDependency:
            for field in embeddingDependency["authentication"]:
                if field in secret_params:
                    model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                        "embedding_dependency"
                    ]["authentication"][field] = "*****"

    if model_args.get("extra_body") is None:
        model_args["extra_body"] = {}
    if user_security_context:  # security component introduced here https://learn.microsoft.com/en-us/azure/defender-for-cloud/gain-end-user-context-ai     
                model_args["extra_body"]["user_security_context"]= user_security_context.to_dict()
    logging.debug(f"REQUEST BODY: {json.dumps(model_args_clean, indent=4)}")

    return model_args


async def promptflow_request(request):
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {app_settings.promptflow.api_key}",
        }
        # Adding timeout for scenarios where response takes longer to come back
        logging.debug(f"Setting timeout to {app_settings.promptflow.response_timeout}")
        async with httpx.AsyncClient(
            timeout=float(app_settings.promptflow.response_timeout)
        ) as client:
            pf_formatted_obj = convert_to_pf_format(
                request,
                app_settings.promptflow.request_field_name,
                app_settings.promptflow.response_field_name
            )
            # NOTE: This only support question and chat_history parameters
            # If you need to add more parameters, you need to modify the request body
            response = await client.post(
                app_settings.promptflow.endpoint,
                json={
                    app_settings.promptflow.request_field_name: pf_formatted_obj[-1]["inputs"][app_settings.promptflow.request_field_name],
                    "chat_history": pf_formatted_obj[:-1],
                },
                headers=headers,
            )
        resp = response.json()
        resp["id"] = request["messages"][-1]["id"]
        return resp
    except Exception as e:
        logging.error(f"An error occurred while making promptflow_request: {e}")


async def process_function_call(response):
    response_message = response.choices[0].message
    messages = []

    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            # Check if function exists
            if tool_call.function.name not in azure_openai_available_tools:
                continue
            
            function_response = await openai_remote_azure_function_call(tool_call.function.name, tool_call.function.arguments)

            # adding assistant response to messages
            messages.append(
                {
                    "role": response_message.role,
                    "function_call": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                    "content": None,
                }
            )
            
            # adding function response to messages
            messages.append(
                {
                    "role": "function",
                    "name": tool_call.function.name,
                    "content": function_response,
                }
            )  # extend conversation with function response
        
        return messages
    
    return None

async def send_chat_request(request_body, request_headers):
    filtered_messages = []
    messages = request_body.get("messages", [])
    for message in messages:
        if message.get("role") != 'tool':
            filtered_messages.append(message)
    request_body['messages'] = filtered_messages
    model_args = prepare_model_args(request_body, request_headers)

    try:
        azure_openai_client = await init_openai_client()
        raw_response = await azure_openai_client.chat.completions.with_raw_response.create(**model_args)
        response = raw_response.parse()
        apim_request_id = raw_response.headers.get("apim-request-id") 
    except Exception as e:
        logging.exception("Exception in send_chat_request")
        raise e

    return response, apim_request_id


async def complete_chat_request(request_body, request_headers):
    if app_settings.base_settings.use_promptflow:
        response = await promptflow_request(request_body)
        history_metadata = request_body.get("history_metadata", {})
        return format_pf_non_streaming_response(
            response,
            history_metadata,
            app_settings.promptflow.response_field_name,
            app_settings.promptflow.citations_field_name
        )
    else:
        response, apim_request_id = await send_chat_request(request_body, request_headers)
        history_metadata = request_body.get("history_metadata", {})
        non_streaming_response = format_non_streaming_response(response, history_metadata, apim_request_id)

        if app_settings.azure_openai.function_call_azure_functions_enabled:
            function_response = await process_function_call(response)  # Add await here

            if function_response:
                request_body["messages"].extend(function_response)

                response, apim_request_id = await send_chat_request(request_body, request_headers)
                history_metadata = request_body.get("history_metadata", {})
                non_streaming_response = format_non_streaming_response(response, history_metadata, apim_request_id)
        citation_count = extract_citation_count_from_response(non_streaming_response)
        score = calculate_trust_score(citation_count=citation_count)
        non_streaming_response = add_trust_metadata_to_response(
            non_streaming_response, score, cache_hit=False, similarity=0.0
        )
    return non_streaming_response

class AzureOpenaiFunctionCallStreamState():
    def __init__(self):
        self.tool_calls = []                # All tool calls detected in the stream
        self.tool_name = ""                 # Tool name being streamed
        self.tool_arguments_stream = ""     # Tool arguments being streamed
        self.current_tool_call = None       # JSON with the tool name and arguments currently being streamed
        self.function_messages = []         # All function messages to be appended to the chat history
        self.streaming_state = "INITIAL"    # Streaming state (INITIAL, STREAMING, COMPLETED)


async def process_function_call_stream(completionChunk, function_call_stream_state, request_body, request_headers, history_metadata, apim_request_id):
    if hasattr(completionChunk, "choices") and len(completionChunk.choices) > 0:
        response_message = completionChunk.choices[0].delta
        
        # Function calling stream processing
        if response_message.tool_calls and function_call_stream_state.streaming_state in ["INITIAL", "STREAMING"]:
            function_call_stream_state.streaming_state = "STREAMING"
            for tool_call_chunk in response_message.tool_calls:
                # New tool call
                if tool_call_chunk.id:
                    if function_call_stream_state.current_tool_call:
                        function_call_stream_state.tool_arguments_stream += tool_call_chunk.function.arguments if tool_call_chunk.function.arguments else ""
                        function_call_stream_state.current_tool_call["tool_arguments"] = function_call_stream_state.tool_arguments_stream
                        function_call_stream_state.tool_arguments_stream = ""
                        function_call_stream_state.tool_name = ""
                        function_call_stream_state.tool_calls.append(function_call_stream_state.current_tool_call)

                    function_call_stream_state.current_tool_call = {
                        "tool_id": tool_call_chunk.id,
                        "tool_name": tool_call_chunk.function.name if function_call_stream_state.tool_name == "" else function_call_stream_state.tool_name
                    }
                else:
                    function_call_stream_state.tool_arguments_stream += tool_call_chunk.function.arguments if tool_call_chunk.function.arguments else ""
                
        # Function call - Streaming completed
        elif response_message.tool_calls is None and function_call_stream_state.streaming_state == "STREAMING":
            function_call_stream_state.current_tool_call["tool_arguments"] = function_call_stream_state.tool_arguments_stream
            function_call_stream_state.tool_calls.append(function_call_stream_state.current_tool_call)
            
            for tool_call in function_call_stream_state.tool_calls:
                tool_response = await openai_remote_azure_function_call(tool_call["tool_name"], tool_call["tool_arguments"])

                function_call_stream_state.function_messages.append({
                    "role": "assistant",
                    "function_call": {
                        "name" : tool_call["tool_name"],
                        "arguments": tool_call["tool_arguments"]
                    },
                    "content": None
                })
                function_call_stream_state.function_messages.append({
                    "tool_call_id": tool_call["tool_id"],
                    "role": "function",
                    "name": tool_call["tool_name"],
                    "content": tool_response,
                })
            
            function_call_stream_state.streaming_state = "COMPLETED"
            return function_call_stream_state.streaming_state
        
        else:
            return function_call_stream_state.streaming_state


async def stream_chat_request(request_body, request_headers):
    response, apim_request_id = await send_chat_request(request_body, request_headers)
    history_metadata = request_body.get("history_metadata", {})
    
    async def generate(apim_request_id, history_metadata):
        if app_settings.azure_openai.function_call_azure_functions_enabled:
            # Maintain state during function call streaming
            function_call_stream_state = AzureOpenaiFunctionCallStreamState()
            
            async for completionChunk in response:
                stream_state = await process_function_call_stream(completionChunk, function_call_stream_state, request_body, request_headers, history_metadata, apim_request_id)
                
                # No function call, asistant response
                if stream_state == "INITIAL":
                    yield format_stream_response(completionChunk, history_metadata, apim_request_id)

                # Function call stream completed, functions were executed.
                # Append function calls and results to history and send to OpenAI, to stream the final answer.
                if stream_state == "COMPLETED":
                    request_body["messages"].extend(function_call_stream_state.function_messages)
                    function_response, apim_request_id = await send_chat_request(request_body, request_headers)
                    async for functionCompletionChunk in function_response:
                        yield format_stream_response(functionCompletionChunk, history_metadata, apim_request_id)
                
        else:
            async for completionChunk in response:
                yield format_stream_response(completionChunk, history_metadata, apim_request_id)

    return generate(apim_request_id=apim_request_id, history_metadata=history_metadata)


async def conversation_internal(request_body, request_headers):
    try:
        if app_settings.azure_openai.stream and not app_settings.base_settings.use_promptflow:
            result = await stream_chat_request(request_body, request_headers)
            response = await make_response(format_as_ndjson(result))
            response.timeout = None
            response.mimetype = "application/json-lines"
            return response
        else:
            result = await complete_chat_request(request_body, request_headers)
            return jsonify(result)

    except Exception as ex:
        logging.exception(ex)
        if hasattr(ex, "status_code"):
            return jsonify({"error": str(ex)}), ex.status_code
        else:
            return jsonify({"error": str(ex)}), 500


@bp.route("/conversation", methods=["POST"])
async def conversation():
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    request_json = await request.get_json()

    return await conversation_internal(request_json, request.headers)


@bp.route("/frontend_settings", methods=["GET"])
def get_frontend_settings():
    try:
        return jsonify(frontend_settings), 200
    except Exception as e:
        logging.exception("Exception in /frontend_settings")
        return jsonify({"error": str(e)}), 500


## Conversation History API ##
@bp.route("/history/generate", methods=["POST"])
async def add_conversation():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        # make sure cosmos is configured
        if not current_app.cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        # check for the conversation_id, if the conversation is not set, we will create a new one
        history_metadata = {}
        if not conversation_id:
            title = await generate_title(request_json["messages"])
            conversation_dict = await current_app.cosmos_conversation_client.create_conversation(
                user_id=user_id, title=title
            )
            conversation_id = conversation_dict["id"]
            history_metadata["title"] = title
            history_metadata["date"] = conversation_dict["createdAt"]

        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_json["messages"]
        if len(messages) > 0 and messages[-1]["role"] == "user":
            createdMessageValue = await current_app.cosmos_conversation_client.create_message(
                uuid=str(uuid.uuid4()),
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1],
            )
            if createdMessageValue == "Conversation not found":
                raise Exception(
                    "Conversation not found for the given conversation ID: "
                    + conversation_id
                    + "."
                )
        else:
            raise Exception("No user message found")
        latest_question = extract_latest_user_question(messages)
        if latest_question:
            matched_question_entry, similarity = await find_similar_cached_answer(
                current_app.cosmos_conversation_client, user_id, latest_question
            )
            if matched_question_entry:
                await current_app.cosmos_conversation_client.increment_question_cache_hit(
                    user_id=user_id, question_entry_id=matched_question_entry["id"]
                )
                history_metadata["conversation_id"] = conversation_id
                cached_score = matched_question_entry.get("trustScore", 0.75)
                cached_quality = {
                    "trust_score": cached_score,
                    "trust_label": trust_label(cached_score),
                    "cache_hit": True,
                    "similarity": round(similarity, 3),
                }
                cached_response = build_cached_response(
                    history_metadata=history_metadata,
                    answer=matched_question_entry.get("answer", ""),
                    quality=cached_quality,
                )
                return jsonify(cached_response), 200
        # Submit request to Chat Completions for response
        request_body = await request.get_json()
        history_metadata["conversation_id"] = conversation_id
        request_body["history_metadata"] = history_metadata
        return await conversation_internal(request_body, request.headers)

    except Exception as e:
        logging.exception("Exception in /history/generate")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/update", methods=["POST"])
async def update_conversation():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        # make sure cosmos is configured
        if not current_app.cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        # check for the conversation_id, if the conversation is not set, we will create a new one
        if not conversation_id:
            raise Exception("No conversation_id found")

        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_json["messages"]
        if len(messages) > 0 and messages[-1]["role"] == "assistant":
            if len(messages) > 1 and messages[-2].get("role", None) == "tool":
                # write the tool message first
                await current_app.cosmos_conversation_client.create_message(
                    uuid=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    input_message=messages[-2],
                )
            # write the assistant message
            await current_app.cosmos_conversation_client.create_message(
                uuid=messages[-1]["id"],
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1],
            )
        else:
            raise Exception("No bot messages found")
        latest_question = None
        try:
            conversation_messages = await current_app.cosmos_conversation_client.get_messages(
                user_id=user_id, conversation_id=conversation_id
            )
            user_messages = [msg for msg in conversation_messages if msg.get("role") == "user"]
            if user_messages:
                latest_question = user_messages[-1].get("content", "")
        except Exception:
            latest_question = None

        if latest_question:
            answer_text = messages[-1].get("content", "")
            citation_count = 0
            if len(messages) > 1 and messages[-2].get("role") == "tool":
                try:
                    tool_payload = json.loads(messages[-2].get("content", "{}"))
                    citation_count = len(tool_payload.get("citations", []))
                except Exception:
                    citation_count = 0
            answer_quality = request_json.get("answer_quality", {})
            trust_score_value = answer_quality.get(
                "trust_score", calculate_trust_score(citation_count)
            )
            await current_app.cosmos_conversation_client.create_question_analytics(
                user_id=user_id,
                conversation_id=conversation_id,
                question=latest_question,
                normalized_question=normalize_question(latest_question),
                answer=answer_text,
                trust_score=trust_score_value,
                citation_count=citation_count,
            )
        # Submit request to Chat Completions for response
        response = {"success": True}
        return jsonify(response), 200

    except Exception as e:
        logging.exception("Exception in /history/update")
        return jsonify({"error": str(e)}), 500

@bp.route("/history/questions", methods=["GET"])
async def list_question_analytics():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]
    limit = request.args.get("limit", default=20, type=int)

    if not current_app.cosmos_conversation_client:
        return jsonify({"error": "CosmosDB is not configured or not working"}), 500

    entries = await current_app.cosmos_conversation_client.get_recent_question_analytics(
        user_id=user_id, limit=limit
    )
    return jsonify(entries), 200


@bp.route("/history/message_feedback", methods=["POST"])
async def update_message():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for message_id
    request_json = await request.get_json()
    message_id = request_json.get("message_id", None)
    message_feedback = request_json.get("message_feedback", None)
    try:
        if not message_id:
            return jsonify({"error": "message_id is required"}), 400

        if not message_feedback:
            return jsonify({"error": "message_feedback is required"}), 400

        ## update the message in cosmos
        updated_message = await current_app.cosmos_conversation_client.update_message_feedback(
            user_id, message_id, message_feedback
        )
        if updated_message:
            return (
                jsonify(
                    {
                        "message": f"Successfully updated message with feedback {message_feedback}",
                        "message_id": message_id,
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "error": f"Unable to update message {message_id}. It either does not exist or the user does not have access to it."
                    }
                ),
                404,
            )

    except Exception as e:
        logging.exception("Exception in /history/message_feedback")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/delete", methods=["DELETE"])
async def delete_conversation():
    await cosmos_db_ready.wait()
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        ## make sure cosmos is configured
        if not current_app.cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        ## delete the conversation messages from cosmos first
        deleted_messages = await current_app.cosmos_conversation_client.delete_messages(
            conversation_id, user_id
        )

        ## Now delete the conversation
        deleted_conversation = await current_app.cosmos_conversation_client.delete_conversation(
            user_id, conversation_id
        )

        return (
            jsonify(
                {
                    "message": "Successfully deleted conversation and messages",
                    "conversation_id": conversation_id,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception("Exception in /history/delete")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/list", methods=["GET"])
async def list_conversations():
    await cosmos_db_ready.wait()
    offset = request.args.get("offset", 0)
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## make sure cosmos is configured
    if not current_app.cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversations from cosmos
    conversations = await current_app.cosmos_conversation_client.get_conversations(
        user_id, offset=offset, limit=25
    )
    if not isinstance(conversations, list):
        return jsonify({"error": f"No conversations for {user_id} were found"}), 404

    ## return the conversation ids

    return jsonify(conversations), 200


@bp.route("/history/read", methods=["POST"])
async def get_conversation():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400

    ## make sure cosmos is configured
    if not current_app.cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversation object and the related messages from cosmos
    conversation = await current_app.cosmos_conversation_client.get_conversation(
        user_id, conversation_id
    )
    ## return the conversation id and the messages in the bot frontend format
    if not conversation:
        return (
            jsonify(
                {
                    "error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."
                }
            ),
            404,
        )

    # get the messages for the conversation from cosmos
    conversation_messages = await current_app.cosmos_conversation_client.get_messages(
        user_id, conversation_id
    )

    ## format the messages in the bot frontend format
    messages = [
        {
            "id": msg["id"],
            "role": msg["role"],
            "content": msg["content"],
            "createdAt": msg["createdAt"],
            "feedback": msg.get("feedback"),
        }
        for msg in conversation_messages
    ]

    return jsonify({"conversation_id": conversation_id, "messages": messages}), 200


@bp.route("/history/rename", methods=["POST"])
async def rename_conversation():
    await cosmos_db_ready.wait()
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400

    ## make sure cosmos is configured
    if not current_app.cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversation from cosmos
    conversation = await current_app.cosmos_conversation_client.get_conversation(
        user_id, conversation_id
    )
    if not conversation:
        return (
            jsonify(
                {
                    "error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."
                }
            ),
            404,
        )

    ## update the title
    title = request_json.get("title", None)
    if not title:
        return jsonify({"error": "title is required"}), 400
    conversation["title"] = title
    updated_conversation = await current_app.cosmos_conversation_client.upsert_conversation(
        conversation
    )

    return jsonify(updated_conversation), 200


@bp.route("/history/delete_all", methods=["DELETE"])
async def delete_all_conversations():
    await cosmos_db_ready.wait()
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    # get conversations for user
    try:
        ## make sure cosmos is configured
        if not current_app.cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        conversations = await current_app.cosmos_conversation_client.get_conversations(
            user_id, offset=0, limit=None
        )
        if not conversations:
            return jsonify({"error": f"No conversations for {user_id} were found"}), 404

        # delete each conversation
        for conversation in conversations:
            ## delete the conversation messages from cosmos first
            deleted_messages = await current_app.cosmos_conversation_client.delete_messages(
                conversation["id"], user_id
            )

            ## Now delete the conversation
            deleted_conversation = await current_app.cosmos_conversation_client.delete_conversation(
                user_id, conversation["id"]
            )
        return (
            jsonify(
                {
                    "message": f"Successfully deleted conversation and messages for user {user_id}"
                }
            ),
            200,
        )

    except Exception as e:
        logging.exception("Exception in /history/delete_all")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/clear", methods=["POST"])
async def clear_messages():
    await cosmos_db_ready.wait()
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        ## make sure cosmos is configured
        if not current_app.cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        ## delete the conversation messages from cosmos
        deleted_messages = await current_app.cosmos_conversation_client.delete_messages(
            conversation_id, user_id
        )

        return (
            jsonify(
                {
                    "message": "Successfully deleted messages in conversation",
                    "conversation_id": conversation_id,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception("Exception in /history/clear_messages")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/ensure", methods=["GET"])
async def ensure_cosmos():
    await cosmos_db_ready.wait()
    if not app_settings.chat_history:
        return jsonify({"error": "CosmosDB is not configured"}), 404

    try:
        success, err = await current_app.cosmos_conversation_client.ensure()
        if not current_app.cosmos_conversation_client or not success:
            if err:
                return jsonify({"error": err}), 422
            return jsonify({"error": "CosmosDB is not configured or not working"}), 500

        return jsonify({"message": "CosmosDB is configured and working"}), 200
    except Exception as e:
        logging.exception("Exception in /history/ensure")
        cosmos_exception = str(e)
        if "Invalid credentials" in cosmos_exception:
            return jsonify({"error": cosmos_exception}), 401
        elif "Invalid CosmosDB database name" in cosmos_exception:
            return (
                jsonify(
                    {
                        "error": f"{cosmos_exception} {app_settings.chat_history.database} for account {app_settings.chat_history.account}"
                    }
                ),
                422,
            )
        elif "Invalid CosmosDB container name" in cosmos_exception:
            return (
                jsonify(
                    {
                        "error": f"{cosmos_exception}: {app_settings.chat_history.conversations_container}"
                    }
                ),
                422,
            )
        else:
            return jsonify({"error": "CosmosDB is not working"}), 500


async def generate_title(conversation_messages) -> str:
    ## make sure the messages are sorted by _ts descending
    title_prompt = "Summarize the conversation so far into a 4-word or less title. Do not use any quotation marks or punctuation. Do not include any other commentary or description."

    messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in conversation_messages
    ]
    messages.append({"role": "user", "content": title_prompt})

    try:
        azure_openai_client = await init_openai_client()
        response = await azure_openai_client.chat.completions.create(
            model=app_settings.azure_openai.model, messages=messages, temperature=1, max_tokens=64
        )

        title = response.choices[0].message.content
        return title
    except Exception as e:
        logging.exception("Exception while generating title", e)
        return messages[-2]["content"]


app = create_app()
