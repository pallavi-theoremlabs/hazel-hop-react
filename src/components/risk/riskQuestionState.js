export function isAnswerEmpty(answer) {
  if (answer?.response_type === 'contacts') {
    const contacts = answer?.response_data?.type === 'contacts' && Array.isArray(answer.response_data.contacts)
      ? answer.response_data.contacts
      : []
    return !contacts.some((contact) => contact && ['name', 'email', 'phone_number', 'linkedin'].some((field) => String(contact[field] || '').trim()))
  }
  return !String(answer?.response || '').trim()
    && !(answer?.selected_option_ids || []).length
    && !answer?.response_data
}

export function isAnswerValid(answer) {
  if (['select_one', 'single_select'].includes(answer?.response_type)) {
    return String(answer?.response || '').trim().length > 0
      && Array.isArray(answer?.selected_option_ids)
      && answer.selected_option_ids.length === 1
  }
  if (['select_multiple', 'multi_select'].includes(answer?.response_type)) {
    return Array.isArray(answer?.selected_option_ids) && answer.selected_option_ids.length > 0
  }
  if (answer?.response_type !== 'contacts') return !isAnswerEmpty(answer)
  const contacts = answer?.response_data?.type === 'contacts' && Array.isArray(answer.response_data.contacts)
    ? answer.response_data.contacts
    : []
  return contacts.length >= 1
    && contacts.length <= 6
    && contacts.every((contact) => {
      const name = String(contact?.name || '').trim()
      const email = String(contact?.email || '').trim()
      const phone = String(contact?.phone_number || '').trim()
      return Boolean(name && (email || phone))
    })
}

export function reviewStateFor(answer) {
  if (isAnswerEmpty(answer)) return 'needs-input'
  if (answer?.reviewed) return 'confirmed'
  return 'review'
}

export function answerFromQuestion(question) {
  return {
    response: question.response ?? '',
    selected_option_ids: question.selected_option_ids ?? null,
    response_data: question.response_data,
    response_type: question.response_type,
    comment: question.comment ?? null,
    reviewed: Boolean(question.reviewed),
  }
}

export function draftAnswer(previous, patch = {}) {
  return { ...previous, ...patch, reviewed: false }
}

export function suggestedAnswerFor(question) {
  const originalResponse = String(question.original_ai_response ?? '').trim()
  if (originalResponse) return originalResponse
  const hasOriginalSelection = Array.isArray(question.original_ai_selected_option_ids)
  const selectedIds = hasOriginalSelection
    ? question.original_ai_selected_option_ids
    : question.selected_option_ids
  const selected = new Set(selectedIds || [])
  const selectedLabels = (question.options || []).filter((option) => selected.has(option.id)).map((option) => option.label).join(', ')
  if (selectedLabels) return selectedLabels
  if (question.original_ai_response != null || hasOriginalSelection) return ''
  if (question.response != null && question.response !== '') return String(question.response)
  return ''
}

export function isMemberEdited(question, answer) {
  const originalIdsAvailable = Array.isArray(question.original_ai_selected_option_ids)
  const isSelect = ['select_one', 'single_select', 'select_multiple', 'multi_select'].includes(question.response_type)
  if (isSelect && originalIdsAvailable) {
    return !sameStringSet(question.original_ai_selected_option_ids, answer?.selected_option_ids || [])
  }

  const originalResponseAvailable = question.original_ai_response != null
  const originalResponse = originalResponseAvailable
    ? String(question.original_ai_response ?? '').trim()
    : String(question.response ?? '').trim()
  const memberResponse = String(answer?.response ?? '').trim()
  return originalResponseAvailable
    ? memberResponse !== originalResponse
    : memberResponse !== String(question.response ?? '').trim()
}

export function textResponseChanged(question, answer) {
  return String(answer?.response ?? '') !== String(question?.response ?? '')
}

export function commentChanged(question, answer) {
  return String(answer?.comment ?? '') !== String(question?.comment ?? '')
}

export function canAcceptSuggestedAnswer(question, answer) {
  const hasSuggestion = Boolean(suggestedAnswerFor(question))
    && (
      question?.is_ai_generated === true
      || question?.original_ai_response != null
      || Array.isArray(question?.original_ai_selected_option_ids)
    )
  return hasSuggestion
    && reviewStateFor(answer) === 'review'
    && isAnswerValid(answer)
    && !isMemberEdited(question, answer)
    && !commentChanged(question, answer)
}

function sameStringSet(left, right) {
  const first = [...new Set((left || []).map(String))].sort()
  const second = [...new Set((right || []).map(String))].sort()
  return first.length === second.length && first.every((value, index) => value === second[index])
}
