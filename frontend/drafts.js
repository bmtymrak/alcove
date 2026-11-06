const prefix = 'alcove:draft:'
const bookCaptureSlot = /^capture:\/books\/([0-9a-f-]{36})\/notes\/new\/(?:\?draft=.+)?$/

export function noteDraft(form) {
  const scope = `${prefix}${form.dataset.draftScope}:`
  const editing = Boolean(form.querySelector('[name="revision"]'))
  const base = window.location.pathname
  const params = new URLSearchParams(window.location.search)
  const slot = editing ? form.dataset.apiUrl : captureSlot(base, params.get('draft'))
  let key = scope + slot
  let recovered = null
  try {
    // Drop drafts from previous sign-ins even in browsers that did not clear storage.
    for (const entry of Object.keys(sessionStorage)) {
      if (entry.startsWith(prefix) && !entry.startsWith(scope)) {
        sessionStorage.removeItem(entry)
      }
    }
    if (!editing) {
      const baseKey = scope + captureSlot(base)
      const alternatives = form.querySelector('[data-other-captures]')
      const availableBooks = new Set(Array.from(form.elements.book.options, option => option.value))
      const removedBookDrafts = base === '/notes/new/' ? Object.keys(sessionStorage)
        .filter(entry => {
          if (!entry.startsWith(scope)) return false
          const match = bookCaptureSlot.exec(entry.slice(scope.length))
          return match && !availableBooks.has(match[1])
        }) : []
      const requested = scope + params.get('source-draft')
      if (removedBookDrafts.includes(requested)) key = requested
      for (const entry of Object.keys(sessionStorage)) {
        if (entry === key) continue
        const removedBook = removedBookDrafts.includes(entry)
        if (!removedBook && entry !== baseKey && !entry.startsWith(baseKey + '?draft=')) continue
        const link = document.createElement('a')
        if (removedBook) {
          link.href = base + '?' + new URLSearchParams({ 'source-draft': entry.slice(scope.length) })
          link.textContent = 'Resume capture from a removed book'
        } else {
          link.href = entry.slice((scope + 'capture:').length)
          link.textContent = entry === baseKey ? 'Resume previous capture' : 'Resume another capture'
        }
        const item = document.createElement('li')
        item.append(link)
        alternatives.append(item)
        alternatives.hidden = false
      }
    }
    if (!form.hasAttribute('data-bound')) {
      recovered = JSON.parse(sessionStorage.getItem(key))
    }
  } catch {
    // Saving online still works when browser storage is disabled.
  }
  window.addEventListener('pageshow', event => {
    if (event.persisted) window.location.reload()
  })
  return {
    recovered,
    nextCapturePath(path, captureId) {
      try {
        // Save and add another always starts fresh, even if the new source
        // already has an unfinished capture at its normal entry point.
        if (sessionStorage.getItem(scope + captureSlot(path))) {
          return `${path}?draft=${encodeURIComponent(captureId)}`
        }
      } catch {
        // The new form remains available when storage is disabled.
      }
      return path
    },
    write(value) {
      try {
        if (value === null) sessionStorage.removeItem(key)
        else sessionStorage.setItem(key, JSON.stringify(value))
        return true
      } catch {
        return false
      }
    },
  }
}

function captureSlot(path, alternative) {
  return 'capture:' + path + (alternative ? `?draft=${encodeURIComponent(alternative)}` : '')
}

export function noteSnapshot(form, picker) {
  const pageText = form.elements.page_number.value.trim()
  const page = Number(pageText)
  return JSON.stringify({
    content: JSON.parse(form.querySelector('[name="content_document"]').value),
    book: form.elements.book.value || null,
    chapter: form.elements.chapter.value || null,
    page_number: pageText && /^[0-9]+$/.test(pageText) && Number.isSafeInteger(page)
      ? page : pageText || null,
    source_reference: form.elements.source_reference.value,
    topic_ids: picker.ids(),
  })
}

export function noteSourceInputs(form) {
  return [
    form.elements.book, form.elements.chapter,
    form.elements.page_number, form.elements.source_reference,
  ]
}
