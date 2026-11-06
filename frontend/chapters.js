const bookPanel = document.querySelector('[data-chapter-book]')
if (bookPanel) {
  manageChapters(bookPanel, {
    currentBook: () => bookPanel.dataset.chapterBook,
    csrf: bookPanel.querySelector('[name="csrfmiddlewaretoken"]').value,
    onSaved() {
      // Reload the server-rendered Chapter context and reading order together.
      history.replaceState({ chaptersOpen: true }, '')
      window.location.reload()
    },
  })
  if (history.state?.chaptersOpen) bookPanel.open = true
}

export function noteChapters(form) {
  const book = form.elements.book
  const chapter = form.elements.chapter
  const panel = form.querySelector('[data-chapter-manager]')
  const options = JSON.parse(document.querySelector('#chapter-options').textContent)
  const csrf = form.elements.csrfmiddlewaretoken.value
  let selectionVersion = 0

  function sync(selected = chapter.value) {
    chapter.replaceChildren(new Option('No chapter', ''))
    for (const item of options[book.value] || []) {
      chapter.add(new Option(item.label, item.id))
    }
    if ([...chapter.options].some(option => option.value === selected)) {
      chapter.value = selected
    }
    panel.hidden = !book.value
  }

  book.addEventListener('input', () => {
    selectionVersion += 1
    panel.open = false
    panel.querySelector('#new-chapter-label').value = ''
    sync()
  })
  chapter.addEventListener('input', () => { selectionVersion += 1 })
  manageChapters(panel, {
    currentBook: () => book.value,
    csrf,
    getSelectionVersion: () => selectionVersion,
    onSaved(bookId, saved, created, previousVersion) {
      if (created) {
        (options[bookId] ||= []).push(saved)
        if (book.value === bookId) {
          const selectNew = !chapter.disabled && selectionVersion === previousVersion
          sync(selectNew ? saved.id : chapter.value)
          if (selectNew) chapter.dispatchEvent(new Event('input'))
        }
      }
    },
    onList(bookId, sequence) {
      options[bookId] = sequence
      sync()
    },
    canSave: () => !chapter.disabled,
  })
  sync()
  return sync
}

function chaptersUrl(bookId) {
  return `/api/v1/books/${bookId}/chapters/`
}

function manageChapters(panel, {
  currentBook, csrf, onSaved, onList = () => {}, canSave = () => true,
  getSelectionVersion = () => null,
}) {
  const list = panel.querySelector('[data-chapter-list]')
  const actions = panel.querySelector('[data-chapter-actions]')
  const newLabel = actions.querySelector('input')
  const add = actions.querySelector('[data-chapter-add]')
  const status = actions.querySelector('[data-chapter-status]')
  let saving = false
  let latestLoad = 0

  async function refresh(bookId) {
    const load = ++latestLoad
    const current = () => load === latestLoad && currentBook() === bookId
    let sequence
    try {
      const response = await fetch(chaptersUrl(bookId))
      if (!response.ok) throw new Error('Could not load chapters.')
      sequence = await response.json()
    } catch (error) {
      if (current()) throw error
      return
    }
    if (!current()) return
    onList(bookId, sequence)
    list.replaceChildren(...sequence.map((chapter, index) => {
      const row = document.createElement('li')
      const label = document.createElement('input')
      label.value = chapter.label
      label.maxLength = 300
      label.setAttribute('aria-label', `Chapter ${chapter.position} label`)
      const rename = () => save(bookId, { label: label.value }, chapter.id)
      handleEnter(label, rename)
      const buttons = document.createElement('div')
      buttons.className = 'chapter-buttons'
      buttons.append(
        button('Save label', `Save chapter ${chapter.position} label`, rename),
        button('Move up', `Move chapter ${chapter.position} up`,
          () => save(bookId, { position: chapter.position - 1 }, chapter.id), index === 0),
        button('Move down', `Move chapter ${chapter.position} down`,
          () => save(bookId, { position: chapter.position + 1 }, chapter.id), index === sequence.length - 1),
      )
      row.append(label, buttons)
      return row
    }))
  }

  async function save(bookId, payload, chapterId = null) {
    if (!bookId || saving || !canSave()) return
    saving = true
    // A list requested before this mutation can arrive after the saved sequence.
    latestLoad += 1
    const created = chapterId === null
    const path = chaptersUrl(bookId) + (created ? '' : chapterId + '/')
    const previousVersion = getSelectionVersion()
    status.textContent = 'Saving chapter…'
    try {
      const response = await fetch(path, {
        method: created ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(payload),
      })
      const result = await response.json()
      if (!response.ok) {
        const field = Object.keys(payload)[0]
        throw new Error(result.error?.fields?.[field]?.[0] || result.error?.message)
      }
      if (created && currentBook() === bookId && newLabel.value === payload.label) {
        newLabel.value = ''
      }
      onSaved(bookId, result, created, previousVersion)
      if (currentBook() === bookId) {
        status.textContent = 'Chapter saved.'
        try {
          await refresh(bookId)
        } catch {
          status.textContent = 'Chapter saved. Reopen this section to refresh the list.'
        }
      }
    } catch (error) {
      if (currentBook() === bookId) {
        status.textContent = error.message || 'Could not confirm the chapter was saved.'
      }
    } finally {
      saving = false
    }
  }

  const append = () => save(currentBook(), { label: newLabel.value })
  add.addEventListener('click', append)
  handleEnter(newLabel, append)
  actions.hidden = false
  panel.addEventListener('toggle', async () => {
    if (!panel.open) return
    const bookId = currentBook()
    status.textContent = ''
    list.replaceChildren()
    try {
      await refresh(bookId)
    } catch {
      status.textContent = 'Could not load chapters.'
    }
  })
}

function button(text, label, action, disabled = false) {
  const control = document.createElement('button')
  control.type = 'button'
  control.textContent = text
  control.setAttribute('aria-label', label)
  control.disabled = disabled
  control.addEventListener('click', action)
  return control
}

function handleEnter(input, action) {
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.isComposing) return
    event.preventDefault()
    action()
  })
}
