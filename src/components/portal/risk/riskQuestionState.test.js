import assert from 'node:assert/strict'
import test from 'node:test'
import {
  answerFromQuestion,
  canAcceptSuggestedAnswer,
  commentChanged,
  draftAnswer,
  isAnswerValid,
  isMemberEdited,
  reviewStateFor,
  suggestedAnswerFor,
  textResponseChanged,
} from './riskQuestionState.js'

const yesNoQuestion = {
  question_id: 'cbqn-test',
  response_type: 'select_one',
  response: 'Yes',
  selected_option_ids: ['yes-id'],
  original_ai_response: 'No',
  original_ai_selected_option_ids: ['no-id'],
  reviewed: true,
  options: [
    { id: 'yes-id', label: 'Yes' },
    { id: 'no-id', label: 'No' },
  ],
}

test('keeps the original Coverbase suggestion when a member selects a different answer', () => {
  const answer = answerFromQuestion(yesNoQuestion)
  assert.equal(suggestedAnswerFor(yesNoQuestion), 'No')
  assert.equal(answer.response, 'Yes')
  assert.equal(isMemberEdited(yesNoQuestion, answer), true)
  assert.equal(reviewStateFor(answer), 'confirmed')
})

test('does not label an unchanged generated answer as member edited', () => {
  const question = {
    ...yesNoQuestion,
    response: 'No',
    selected_option_ids: ['no-id'],
  }
  assert.equal(isMemberEdited(question, answerFromQuestion(question)), false)
})

test('offers Accept suggested answer only for an untouched populated suggestion requiring review', () => {
  const question = {
    ...yesNoQuestion,
    response: 'No',
    selected_option_ids: ['no-id'],
    original_ai_response: undefined,
    original_ai_selected_option_ids: undefined,
    is_ai_generated: true,
    reviewed: false,
  }
  const answer = answerFromQuestion(question)
  assert.equal(canAcceptSuggestedAnswer(question, answer), true)
  assert.equal(canAcceptSuggestedAnswer(question, draftAnswer(answer, { response: 'Yes', selected_option_ids: ['yes-id'] })), false)
})

test('unchanged text and comment values do not qualify for blur saves', () => {
  const question = { response: 'Existing answer', comment: 'Existing comment' }
  const answer = { response: 'Existing answer', comment: 'Existing comment' }
  assert.equal(textResponseChanged(question, answer), false)
  assert.equal(commentChanged(question, answer), false)
  assert.equal(textResponseChanged(question, { ...answer, response: 'Updated answer' }), true)
  assert.equal(commentChanged(question, { ...answer, comment: 'Updated comment' }), true)
})

test('empty contacts remain Needs input and are not valid for Confirm all', () => {
  const answer = {
    response_type: 'contacts',
    response: 'No contact response is available.',
    response_data: { type: 'contacts', contacts: [] },
    reviewed: true,
  }
  assert.equal(isAnswerValid(answer), false)
  assert.equal(reviewStateFor(answer), 'needs-input')
})

test('a failed save can retain the member draft without showing Confirmed', () => {
  const previous = answerFromQuestion({ ...yesNoQuestion, response: 'No', selected_option_ids: ['no-id'] })
  const attempted = draftAnswer(previous, { response: 'Yes', selected_option_ids: ['yes-id'] })
  const retainedAfterFailure = draftAnswer(attempted)
  assert.equal(retainedAfterFailure.response, 'Yes')
  assert.deepEqual(retainedAfterFailure.selected_option_ids, ['yes-id'])
  assert.equal(retainedAfterFailure.reviewed, false)
  assert.equal(reviewStateFor(retainedAfterFailure), 'review')
})

test('a Coverbase reload restores the saved institution answer and original suggestion', () => {
  const reloaded = answerFromQuestion(yesNoQuestion)
  assert.equal(reloaded.response, 'Yes')
  assert.equal(suggestedAnswerFor(yesNoQuestion), 'No')
  assert.equal(isMemberEdited(yesNoQuestion, reloaded), true)
})
