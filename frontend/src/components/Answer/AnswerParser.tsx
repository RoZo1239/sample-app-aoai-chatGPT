import { cloneDeep } from 'lodash'

import { AskResponse, Citation } from '../../api'

export type ParsedAnswer = {
  citations: Citation[]
  markdownFormatText: string
  summaryText: string | null
  detailsText: string | null
  generated_chart: string | null
} | null

const DEAD_END_PATTERNS: RegExp[] = [
  /the\s+requested\s+information\s+is\s+not\s+(?:available|found)\s+in\s+the\s+retrieved\s+data\.?(?:\s*please\s+try\s+(?:a\s+)?(?:another|different)\s+(?:query|search|question)\s+or\s+(?:topic|keyword)\.?)?/gi,
  /please\s+try\s+(?:a\s+)?(?:another|different)\s+(?:query|search|question)\s+or\s+(?:topic|keyword)\.?/gi,
  /(?:i\s+)?(?:could\s+not|can'?t|cannot)\s+find\s+(?:that|relevant\s+information|any\s+(?:relevant\s+)?information)\s+in\s+the\s+retrieved\s+(?:data|results|documents)\.?/gi,
  /no\s+(?:relevant\s+)?(?:results|documents|information)\s+(?:were\s+)?found\s+in\s+the\s+retrieved\s+(?:data|results|documents)\.?/gi,
  /(?:based\s+on\s+the\s+retrieved\s+(?:data|results|documents),?\s+)?i\s+(?:was\s+unable|am\s+unable|cannot)\s+to\s+(?:locate|find)\s+(?:any\s+)?(?:relevant\s+)?information\.?/gi,
  /the\s+retrieved\s+(?:data|results|documents)\s+(?:do(?:es)?)\s+not\s+(?:contain|include|have)\s+(?:any\s+)?(?:relevant\s+)?(?:information|data)[^.]*\./gi,
  /(?:unfortunately,?\s+)?there\s+(?:is|are)\s+no\s+(?:relevant\s+)?(?:results?|documents?|information|data)\s+(?:available\s+)?in\s+the\s+retrieved[^.]*\./gi,
]

const DEAD_END_REPLACEMENT =
  "I don't have all the details on that one, but the MilVet Navigator team can help. Reach out at info@milvetnavigator.com or click **'Schedule a Demo'** or **'Schedule a Meeting'** in the top-right corner."

function sanitizeDeadEnds(text: string): string {
  let result = text
  for (const pattern of DEAD_END_PATTERNS) {
    result = result.replace(pattern, DEAD_END_REPLACEMENT)
  }
  return result
}

// Filler enforcement — guaranteed opening regardless of model output
const FILLER_OPENING_RE = /^(?:here'?s\s+the\s+key|good\s+question|let'?s\s+break|in\s+simple\s+terms|from\s+what\s+i\s+can\s+see|this\s+is\s+what'?s\s+happening|it\s+looks\s+like)/i
const FILLER_POOL = [
  "Here's the key idea: ",
  "From what I can see, ",
  "Let's break this down: ",
  "In simple terms, ",
]
let _fillerIdx = 0
function enforceOpeningFiller(text: string): string {
  // Skip for loading placeholder and fragments too short to evaluate
  if (text.length < 60) return text
  if (FILLER_OPENING_RE.test(text.trimStart())) return text
  const filler = FILLER_POOL[_fillerIdx % FILLER_POOL.length]
  _fillerIdx++
  return filler + text
}

export const enumerateCitations = (citations: Citation[]) => {
  const filepathMap = new Map()
  for (const citation of citations) {
    const { filepath } = citation
    let part_i = 1
    if (filepathMap.has(filepath)) {
      part_i = filepathMap.get(filepath) + 1
    }
    filepathMap.set(filepath, part_i)
    citation.part_index = part_i
  }
  return citations
}

export function parseAnswer(answer: AskResponse): ParsedAnswer {
  if (typeof answer.answer !== "string") return null
  let answerText = answer.answer
  const citationLinks = answerText.match(/\[(doc\d\d?\d?)]/g)

  const lengthDocN = '[doc'.length

  let filteredCitations = [] as Citation[]
  let citationReindex = 0
  citationLinks?.forEach(link => {
    const citationIndex = link.slice(lengthDocN, link.length - 1)
    const citation = cloneDeep(answer.citations[Number(citationIndex) - 1]) as Citation
    if (!filteredCitations.find(c => c.id === citationIndex) && citation) {
      answerText = answerText.replaceAll(link, ` ^${++citationReindex}^ `)
      citation.id = citationIndex
      citation.reindex_id = citationReindex.toString()
      filteredCitations.push(citation)
    } else if (!citation) {
      answerText = answerText.replaceAll(link, '')
    }
  })

  filteredCitations = enumerateCitations(filteredCitations)
  answerText = sanitizeDeadEnds(answerText)
  answerText = answerText.replace(/\s*—\s*/g, ' ')
  answerText = answerText.replace(
    /\binfo@milvetnavigator\.com\b/gi,
    '[info@milvetnavigator.com](https://milvetnavigator.com/contact/)'
  )

  // Enforce conversational opening filler
  answerText = enforceOpeningFiller(answerText)

  // Split on [EXPAND_START] marker if the model included it
  const EXPAND_MARKER = '[EXPAND_START]'
  const boundaryIdx = answerText.indexOf(EXPAND_MARKER)
  let summaryText: string | null = null
  let detailsText: string | null = null

  if (boundaryIdx !== -1) {
    summaryText = answerText.slice(0, boundaryIdx).trim()
    detailsText = answerText.slice(boundaryIdx + EXPAND_MARKER.length).trim()
    answerText = summaryText + '\n\n' + detailsText
  } else if (answerText.length > 200) {
    // Auto-split fallback: find the first paragraph break after 150 chars
    const splitIdx = answerText.indexOf('\n\n', 150)
    if (splitIdx !== -1 && splitIdx < answerText.length - 80) {
      summaryText = answerText.slice(0, splitIdx).trim()
      detailsText = answerText.slice(splitIdx).trim()
    }
  }

  return {
    citations: filteredCitations,
    markdownFormatText: answerText,
    summaryText,
    detailsText,
    generated_chart: answer.generated_chart
  }
}

