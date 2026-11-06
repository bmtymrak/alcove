import { noteSnapshot, noteSourceInputs } from './drafts'

export function explicitCapture(form, editor, draft, initialBook) {
  const id = form.querySelector('[name="capture_id"]')
  const book = form.querySelector('[name="book"]')
  const sourceInputs = noteSourceInputs(form)
  const status = form.querySelector('#save-status')
  const message = form.querySelector('#editor-error')
  const toolbar = form.querySelector('#formatting-tools')
  let pending = draft.recovered?.captureId ? draft.recovered : null
  let saving = false
  let persisted = true

  function persist() {
    const unsaved = !editor.isEmpty || (book.value || null) !== initialBook
      || form.elements.page_number.value || form.elements.source_reference.value
      || form.hasAttribute('data-bound')
    const value = unsaved
      ? { snapshot: noteSnapshot(form) }
      : null
    persisted = draft.write(pending || value)
  }

  function lockInput(locked) {
    sourceInputs.forEach(input => { input.disabled = locked })
    toolbar.querySelectorAll('button').forEach(button => { button.disabled = locked })
    editor.setEditable(!locked)
  }

  function unconfirmed() {
    lockInput(true)
    status.textContent = 'Save not confirmed.'
    message.textContent = 'Retry saving to confirm this capture. Your draft is still here.'
    message.hidden = false
  }

  if (pending) unconfirmed()
  sourceInputs.forEach(input => input.addEventListener('input', persist))
  window.addEventListener('beforeunload', event => {
    if (!persisted) {
      event.preventDefault()
      event.returnValue = ''
    }
  })
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (saving) return
    const another = event.submitter?.name === 'add_another'
    const buttons = form.querySelectorAll('[data-explicit-save], [name="add_another"]')
    pending ||= { snapshot: noteSnapshot(form), captureId: id.value }
    const payload = JSON.parse(pending.snapshot)
    persist()
    saving = true
    buttons.forEach(button => { button.disabled = true })
    lockInput(true)
    status.textContent = 'Saving…'
    message.hidden = true
    let confirmed = false
    try {
      const response = await fetch(form.dataset.apiUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
        },
        body: JSON.stringify({ ...payload, capture_id: pending.captureId }),
      })
      const result = await response.json()
      if ((response.status === 400 && result.error?.code === 'invalid')
        || (response.status === 409 && result.error?.code === 'capture_conflict')) {
        pending = null
        persist()
        lockInput(false)
        message.textContent = response.status === 409
          ? `${result.error.message} Reload this draft to start a new capture.`
          : result.error.message
        message.hidden = false
        status.textContent = 'Not saved. Your draft is still here.'
        return
      }
      if (![200, 201].includes(response.status) || typeof result.id !== 'string') {
        throw new Error('Save not confirmed')
      }
      draft.write(null)
      persisted = true
      confirmed = true
      status.textContent = 'Saved.'
      const nextCapture = payload.book ? `/books/${payload.book}/notes/new/` : '/notes/new/'
      window.location.assign(another
        ? draft.nextCapturePath(nextCapture, pending.captureId)
        : `/notes/${result.id}/`)
    } catch {
      unconfirmed()
    } finally {
      if (!confirmed) {
        saving = false
        buttons.forEach(button => { button.disabled = false })
      }
    }
  })
  return persist
}
