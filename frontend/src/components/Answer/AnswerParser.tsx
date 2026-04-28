import { cloneDeep } from 'lodash'

import { AskResponse, Citation } from '../../api'

export type ParsedAnswer = {
  citations: Citation[]
  markdownFormatText: string,
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
  "I don't have all the details on that one, but the MilVet Navigator team can help — reach out at info@milvetnavigator.com or click **'Schedule a Demo'** or **'Schedule a Meeting'** in the top-right corner."

function sanitizeDeadEnds(text: string): string {
  let result = text
  for (const pattern of DEAD_END_PATTERNS) {
    result = result.replace(pattern, DEAD_END_REPLACEMENT)
  }
  return result
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
      // Citation index has no matching entry — strip the raw marker from the text
      answerText = answerText.replaceAll(link, '')
    }
  })

  filteredCitations = enumerateCitations(filteredCitations)
  answerText = sanitizeDeadEnds(answerText)
  // Convert bare MVN email addresses to clickable booking links
  answerText = answerText.replace(
    /\binfo@milvetnavigator\.com\b/gi,
    '[info@milvetnavigator.com](https://outlook.office.com/bookwithme/user/4b7fbc393660415583a4a4eac09e3bfc%40milvetnavigator.com/booking/HOgA9kJb-0SXfHHK6rOZGw2?anonymous&ismsaljsauthenabled=true)'
  )

  return {
    citations: filteredCitations,
    markdownFormatText: answerText,
    generated_chart: answer.generated_chart
  }
}
