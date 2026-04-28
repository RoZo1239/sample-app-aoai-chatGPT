import os
import json
import logging
import re
import requests
import dataclasses

from typing import List

DEBUG = os.environ.get("DEBUG", "false")
if DEBUG.lower() == "true":
    logging.basicConfig(level=logging.DEBUG)

AZURE_SEARCH_PERMITTED_GROUPS_COLUMN = os.environ.get(
    "AZURE_SEARCH_PERMITTED_GROUPS_COLUMN"
)

_OFFICIAL_EMAIL = os.environ.get("MVN_SUPPORT_EMAIL", "info@milvetnavigator.com")
_MVN_EMAIL_RE = re.compile(r'[\w.-]+@milvetnavigator\.com', re.IGNORECASE)
_PHONE_RE = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
_CONTACT_NAME_RE = re.compile(
    r'(Point\s+of\s+Contact(?:\s+Name)?\s*:\s*)(\S+(?:\s+\S+)?)',
    re.IGNORECASE,
)
_LEGACY_CONTACT_NAME_RE = re.compile(r'\bMahdi\s+Omar\b', re.IGNORECASE)
_MONEY_RE = re.compile(
    r"""(
        (?:US\$|\$)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|b|thousand|million|billion))?
        (?:\s?(?:-|to|–)\s?(?:US\$|\$)?\s?\d[\d,]*(?:\.\d+)?)?
        |
        \b\d[\d,]*(?:\.\d+)?\s?(?:USD|US\s*dollars?|dollars?)\b
        (?:\s?(?:-|to|–)\s?\d[\d,]*(?:\.\d+)?\s?(?:USD|US\s*dollars?|dollars?))?
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_EMAIL_PLACEHOLDER_RE = re.compile(r"\{+\s*MVN_SUPPORT_EMAIL\s*\}+")
_MONEY_REPLACEMENT = (
    "For pricing or financial details, please contact the MilVet Navigator team at "
    + _OFFICIAL_EMAIL
)

_PRICING_CONTEXT_RE = re.compile(
    r"""(
        (?:annual|monthly|subscription)\s+(?:cost|price|fee|pricing)\s+(?:ranges?|starts?|is|are)\s+from
        |
        (?:pricing|cost)\s+(?:ranges?|model|structure|tier|plan)
        |
        (?:ranges?\s+from\s+(?:US\$|\$)|\bstarts?\s+at\s+(?:US\$|\$))
        |
        (?:institutional\s+subscription\s+cost)
        |
        (?:depending\s+on\s+(?:factors?\s+such\s+as|the\s+size))
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_RETRIEVAL_DEAD_END_RE = re.compile(
    r"""(?:
        (?:the\s+)?requested\s+information\s+is\s+not\s+(?:available|found)\s+in\s+the\s+retrieved\s+data
        |
        not\s+(?:available|found)\s+in\s+the\s+retrieved\s+(?:data|results|documents)
        |
        please\s+try\s+(?:a\s+)?(?:another|different)\s+(?:query|search|question)\s+or\s+(?:topic|keyword)
        |
        (?:i\s+)?(?:could\s+not|can'?t|cannot)\s+find\s+(?:that|relevant\s+information|any\s+(?:relevant\s+)?information)\s+in\s+the\s+retrieved\s+(?:data|results|documents)
        |
        no\s+(?:relevant\s+)?(?:results|documents|information)\s+(?:were\s+)?found\s+in\s+the\s+retrieved\s+(?:data|results|documents)
        |
        (?:based\s+on\s+the\s+retrieved\s+(?:data|results|documents),?\s+)?i\s+(?:was\s+unable|am\s+unable|cannot)\s+to\s+(?:locate|find)\s+(?:any\s+)?(?:relevant\s+)?information
        |
        the\s+retrieved\s+(?:data|results|documents)\s+(?:do(?:es)?)\s+not\s+(?:contain|include|have)\s+(?:any\s+)?(?:relevant\s+)?(?:information|data)
        |
        (?:unfortunately,?\s+)?there\s+(?:is|are)\s+no\s+(?:relevant\s+)?(?:results?|documents?|information|data)\s+(?:available\s+)?in\s+the\s+retrieved
        |
        i\s+(?:was\s+)?unable\s+to\s+find\s+(?:any\s+)?(?:relevant\s+)?information\s+(?:about|on|for|regarding)\s+(?:this|that)\s+(?:topic|query|question)
    )[.!?]?""",
    re.IGNORECASE | re.VERBOSE,
)
_RETRIEVAL_DEAD_END_REPLACEMENT = (
    f"I want to make sure you get accurate details. I don't see enough verified context for that yet, "
    f"but the MilVet Navigator team can help right away at {_OFFICIAL_EMAIL}. "
    f"You can also use the Schedule a Demo or Schedule a Meeting buttons in the top-right corner."
)
# Pre-compiled pattern to collapse duplicate dead-end replacements
_DEAD_END_DEDUP_RE = re.compile(
    r'(' + re.escape(_RETRIEVAL_DEAD_END_REPLACEMENT) + r')(\s*' + re.escape(_RETRIEVAL_DEAD_END_REPLACEMENT) + r')+',
)
# Em dash pattern for prose sanitization
_EM_DASH_RE = re.compile(r'\s*—\s*')

# Detects if response already opens with an approved conversational filler
_FILLER_OPENING_RE = re.compile(
    r"""^\s*(?:
        here'?s\s+the\s+key\s+idea
        |good\s+question
        |let'?s\s+break\s+this\s+down
        |in\s+simple\s+terms
        |from\s+what\s+i\s+can\s+see
        |this\s+is\s+what'?s\s+happening
        |it\s+looks\s+like
        |great\s+question
        |sure[,!]
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_FILLER_ROTATION = [
    "Here's the key idea: ",
    "From what I can see, ",
    "Let's break this down: ",
    "In simple terms, ",
]
_filler_counter = 0

def enforce_opening_filler(content: str) -> str:
    """Prepend a conversational filler if the response does not already open with one."""
    global _filler_counter
    if not content or _FILLER_OPENING_RE.match(content):
        return content
    filler = _FILLER_ROTATION[_filler_counter % len(_FILLER_ROTATION)]
    _filler_counter += 1
    return filler + content

def sanitize_response_content(content):
    if not content:
        return content
    content = _EMAIL_PLACEHOLDER_RE.sub(_OFFICIAL_EMAIL, content)
    if _MONEY_RE.search(content) or _PRICING_CONTEXT_RE.search(content):
        return _MONEY_REPLACEMENT
    content = _MVN_EMAIL_RE.sub(_OFFICIAL_EMAIL, content)
    content = _PHONE_RE.sub(_OFFICIAL_EMAIL, content)
    content = _CONTACT_NAME_RE.sub(r'\1MilVet Navigator team', content)
    content = _LEGACY_CONTACT_NAME_RE.sub("MilVet Navigator team", content)
    content = _RETRIEVAL_DEAD_END_RE.sub(_RETRIEVAL_DEAD_END_REPLACEMENT, content)
    content = _DEAD_END_DEDUP_RE.sub(r'\1', content)
    content = _EM_DASH_RE.sub(' ', content)
    return content


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


async def format_as_ndjson(r):
    try:
        async for event in r:
            yield json.dumps(event, cls=JSONEncoder) + "\n"
    except Exception as error:
        logging.exception("Exception while generating response stream: %s", error)
        yield json.dumps({"error": str(error)})


def parse_multi_columns(columns: str) -> list:
    if "|" in columns:
        return columns.split("|")
    else:
        return columns.split(",")


def fetchUserGroups(userToken, nextLink=None):
    # Recursively fetch group membership
    if nextLink:
        endpoint = nextLink
    else:
        endpoint = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$select=id"

    headers = {"Authorization": "bearer " + userToken}
    try:
        r = requests.get(endpoint, headers=headers)
        if r.status_code != 200:
            logging.error(f"Error fetching user groups: {r.status_code} {r.text}")
            return []

        r = r.json()
        if "@odata.nextLink" in r:
            nextLinkData = fetchUserGroups(userToken, r["@odata.nextLink"])
            r["value"].extend(nextLinkData)

        return r["value"]
    except Exception as e:
        logging.error(f"Exception in fetchUserGroups: {e}")
        return []


def generateFilterString(userToken):
    # Get list of groups user is a member of
    userGroups = fetchUserGroups(userToken)

    # Construct filter string
    if not userGroups:
        logging.debug("No user groups found")

    group_ids = ", ".join([obj["id"] for obj in userGroups])
    return f"{AZURE_SEARCH_PERMITTED_GROUPS_COLUMN}/any(g:search.in(g, '{group_ids}'))"


def format_non_streaming_response(chatCompletion, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletion.id,
        "model": chatCompletion.model,
        "created": chatCompletion.created,
        "object": chatCompletion.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletion.choices) > 0:
        message = chatCompletion.choices[0].message
        if message:
            if hasattr(message, "context"):
                response_obj["choices"][0]["messages"].append(
                    {
                        "role": "tool",
                        "content": sanitize_response_content(json.dumps(message.context)),
                    }
                )
            response_obj["choices"][0]["messages"].append(
                {
                    "role": "assistant",
                    "content": enforce_opening_filler(sanitize_response_content(message.content)),
                }
            )
            return response_obj

    return {}

def format_stream_response(chatCompletionChunk, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletionChunk.id,
        "model": chatCompletionChunk.model,
        "created": chatCompletionChunk.created,
        "object": chatCompletionChunk.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletionChunk.choices) > 0:
        delta = chatCompletionChunk.choices[0].delta
        if delta:
            if hasattr(delta, "context"):
                messageObj = {"role": "tool", "content": sanitize_response_content(json.dumps(delta.context))}
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            if delta.role == "assistant" and hasattr(delta, "context"):
                messageObj = {
                    "role": "assistant",
                    "context": delta.context,
                }
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            if delta.tool_calls:
                messageObj = {
                    "role": "tool",
                    "tool_calls": {
                        "id": delta.tool_calls[0].id,
                        "function": {
                            "name" : delta.tool_calls[0].function.name,
                            "arguments": delta.tool_calls[0].function.arguments
                        },
                        "type": delta.tool_calls[0].type
                    }
                }
                if hasattr(delta, "context"):
                    messageObj["context"] = sanitize_response_content(json.dumps(delta.context))
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            else:
                if delta.content:
                    messageObj = {"role": "assistant", "content": sanitize_response_content(delta.content)}
                    response_obj["choices"][0]["messages"].append(messageObj)
                    return response_obj

    return {}


def format_pf_non_streaming_response(
    chatCompletion, history_metadata, response_field_name, citations_field_name, message_uuid=None
):
    if chatCompletion is None:
        logging.error(
            "chatCompletion object is None - Increase PROMPTFLOW_RESPONSE_TIMEOUT parameter"
        )
        return {
            "error": "No response received from promptflow endpoint increase PROMPTFLOW_RESPONSE_TIMEOUT parameter or check the promptflow endpoint."
        }
    if "error" in chatCompletion:
        logging.error(f"Error in promptflow response api: {chatCompletion['error']}")
        return {"error": chatCompletion["error"]}

    logging.debug(f"chatCompletion: {chatCompletion}")
    try:
        messages = []
        if response_field_name in chatCompletion:
            messages.append({
                "role": "assistant",
                "content": sanitize_response_content(chatCompletion[response_field_name]) 
            })
        if citations_field_name in chatCompletion:
            citation_content= {"citations": chatCompletion[citations_field_name]}
            messages.append({ 
                "role": "tool",
                "content": sanitize_response_content(json.dumps(citation_content))
            })

        response_obj = {
            "id": chatCompletion["id"],
            "model": "",
            "created": "",
            "object": "",
            "history_metadata": history_metadata,
            "choices": [
                {
                    "messages": messages,
                }
            ]
        }
        return response_obj
    except Exception as e:
        logging.error(f"Exception in format_pf_non_streaming_response: {e}")
        return {}


def convert_to_pf_format(input_json, request_field_name, response_field_name):
    output_json = []
    logging.debug(f"Input json: {input_json}")
    # align the input json to the format expected by promptflow chat flow
    for message in input_json["messages"]:
        if message:
            if message["role"] == "user":
                new_obj = {
                    "inputs": {request_field_name: message["content"]},
                    "outputs": {response_field_name: ""},
                }
                output_json.append(new_obj)
            elif message["role"] == "assistant" and len(output_json) > 0:
                output_json[-1]["outputs"][response_field_name] = message["content"]
    logging.debug(f"PF formatted response: {output_json}")
    return output_json


def comma_separated_string_to_list(s: str) -> List[str]:
    '''
    Split comma-separated values into a list.
    '''
    return s.strip().replace(' ', '').split(',')

