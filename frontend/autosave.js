import { noteSnapshot, noteSourceInputs } from './drafts'

// Existing Notes use revision-checked saves; creation remains an explicit action.
export function autosave(form, draft) {
  const revision = form.querySelector('[name="revision"]')
  const book = form.querySelector('[name="book"]')
  const status = form.querySelector('#save-status')
  const message = form.querySelector('#editor-error')
  const retry = form.querySelector('[data-retry-save]')
  const review = form.querySelector('[data-review-conflict]')
  const conflict = form.querySelector('#save-conflict')
  const resolve = form.querySelector('[data-resolve-conflict]')
  const snapshot = () => noteSnapshot(form)
  let blocked = form.dataset.saveState === 'saved' ? null : form.dataset.saveState
  let saved = blocked ? null : snapshot()
  if (draft.recovered) {
    const currentRevision = Number(revision.value)
    revision.value = draft.recovered.revision
    blocked = currentRevision === draft.recovered.revision ? draft.recovered.blocked : 'conflict'
    saved = null
  }
  let saving = false
  let persisted = true
  let timer
  let reviewedRevision

  function showState(state) {
    status.textContent = {
      saved: 'Saved.', saving: 'Saving…',
      failed: 'Not saved. Your draft is still here.',
      conflict: 'Conflict. Your draft is still here.',
    }[state]
    retry.hidden = state !== 'failed'
    review.hidden = state !== 'conflict'
  }

  function changed() {
    clearTimeout(timer)
    persist()
    if (blocked) return
    if (snapshot() === saved && !saving) {
      showState('saved')
      return
    }
    showState('saving')
    timer = setTimeout(save, 500)
  }

  function persist() {
    const pending = snapshot()
    persisted = draft.write(pending === saved && !saving ? null : {
      snapshot: pending, revision: Number(revision.value), blocked,
    })
  }

  async function save() {
    clearTimeout(timer)
    if (saving || blocked) return
    const pending = snapshot()
    if (pending === saved) {
      showState('saved')
      return
    }
    saving = true
    persist()
    showState('saving')
    message.hidden = true
    try {
      const response = await fetch(form.dataset.apiUrl, {
        method: 'PATCH', credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
        },
        body: JSON.stringify({ ...JSON.parse(pending), revision: Number(revision.value) }),
      })
      const result = await response.json()
      if (!response.ok) {
        saved = null
        blocked = response.status === 409 ? 'conflict' : 'failed'
        message.textContent = result.error?.message || 'Could not save your changes.'
        message.hidden = false
        showState(blocked)
        return
      }
      if (!Number.isSafeInteger(result.revision) || result.revision <= Number(revision.value)) {
        throw new Error('Save not confirmed')
      }
      revision.value = result.revision
      saved = pending
      conflict.hidden = true
      showState(snapshot() === saved ? 'saved' : 'saving')
    } catch {
      // The write may have committed even when its response was lost. A retry
      // must check the revision, including when the owner undid their edits.
      saved = null
      blocked = 'failed'
      message.textContent = 'Could not confirm saving. Your draft is still here. Retry to check the saved revision.'
      message.hidden = false
      showState(blocked)
    } finally {
      saving = false
      persist()
      // A response only confirms the snapshot sent, never text typed while waiting.
      if (!blocked && snapshot() !== saved) void save()
    }
  }

  retry.addEventListener('click', () => {
    blocked = null
    void save()
  })
  review.addEventListener('click', async () => {
    review.disabled = true
    resolve.hidden = true
    try {
      const response = await fetch(form.dataset.apiUrl, { credentials: 'same-origin' })
      if (!response.ok) throw new Error('Review failed')
      const current = await response.json()
      reviewedRevision = current.revision
      conflict.querySelector('[data-current-content]').textContent = current.plain_text
      const source = [...book.options].find(option => option.value === (current.book || ''))
      conflict.querySelector('[data-current-source]').textContent = source?.textContent || current.book
      conflict.querySelector('[data-current-chapter]').textContent = current.chapter_label || '—'
      conflict.querySelector('[data-current-page]').textContent = current.page_number ?? '—'
      conflict.querySelector('[data-current-reference]').textContent = current.source_reference || '—'
      conflict.querySelector('[data-current-revision]').textContent = current.revision
      conflict.hidden = false
      resolve.hidden = false
    } catch {
      message.textContent = 'Could not load the current Note. Your draft is still here. Try reviewing again.'
      message.hidden = false
    } finally {
      review.disabled = false
    }
  })
  resolve.addEventListener('click', () => {
    revision.value = reviewedRevision
    blocked = null
    resolve.hidden = true
    void save()
  })
  form.addEventListener('submit', event => {
    event.preventDefault()
    if (!blocked) void save()
  })
  noteSourceInputs(form).forEach(input => input.addEventListener('input', changed))
  window.addEventListener('beforeunload', event => {
    if (!persisted && (snapshot() !== saved || saving)) {
      event.preventDefault()
      event.returnValue = ''
    }
  })
  form.querySelector('[data-explicit-save]').hidden = true
  showState(blocked || 'saved')
  if (draft.recovered || blocked) changed()
  return changed
}
