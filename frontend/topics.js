export function topicPicker(form, recovered, changed) {
  const fieldset = form.querySelector('[data-topic-picker]')
  const input = fieldset.querySelector('input[type="search"]')
  const suggestions = fieldset.querySelector('#topic-suggestions')
  const selection = fieldset.querySelector('[data-topic-selection]')
  const feedback = fieldset.querySelector('[data-topic-feedback]')
  const data = JSON.parse(fieldset.querySelector('#topic-picker-data').textContent)
  const options = new Map(data.options.map(topic => [topic.id, topic]))
  const selected = new Set(data.assigned)
  let shown = new Map()
  let timer
  let requestId = 0

  function assign(topic, matching = options) {
    options.set(topic.id, topic)
    for (const id of selected) {
      if (topic.ancestors.includes(id) || matching.get(id)?.ancestors.includes(topic.id)) {
        selected.delete(id)
      }
    }
    selected.add(topic.id)
  }

  function renderSelection() {
    const names = new Map([...selected].map(id => [
      id, options.get(id)?.full_path || 'Unavailable Topic',
    ]))
    if (names.size === shown.size && [...names].every(([id, name]) => shown.get(id) === name)) {
      return false
    }
    shown = names
    selection.replaceChildren()
    const sorted = [...names].sort(([, first], [, second]) => first.localeCompare(second))
    for (const [id, name] of sorted) {
      const item = document.createElement('li')
      const button = document.createElement('button')
      button.type = 'button'
      button.textContent = 'Remove'
      button.setAttribute('aria-label', `Remove ${name}`)
      button.addEventListener('click', () => {
        selected.delete(id)
        renderSelection()
        input.focus()
        refresh()
        changed()
      })
      item.append(name, ' ', button)
      selection.append(item)
    }
    return true
  }

  function refresh() {
    clearTimeout(timer)
    const query = input.value.trim()
    const id = ++requestId
    suggestions.replaceChildren()
    feedback.textContent = ''
    if (!query) return
    timer = setTimeout(async () => {
      try {
        const url = new URL(fieldset.dataset.topicsUrl, location.origin)
        url.searchParams.set('q', query)
        const response = await fetch(url, { credentials: 'same-origin' })
        if (!response.ok) throw new Error('Topic search failed')
        const matches = await response.json()
        if (id !== requestId) return
        // A path match includes all its descendants. Use the fresh matches
        // rather than cached ancestry for Topics that may have been moved.
        const matching = new Map(matches.map(topic => [topic.id, topic]))
        for (const topic of matches) {
          options.set(topic.id, topic)
          if (selected.has(topic.id)) continue
          const item = document.createElement('li')
          const button = document.createElement('button')
          button.type = 'button'
          button.textContent = topic.full_path
          button.addEventListener('click', () => {
            assign(topic, matching)
            renderSelection()
            input.value = ''
            refresh()
            input.focus()
            changed()
          })
          item.append(button)
          suggestions.append(item)
        }
        renderSelection()
        feedback.textContent = suggestions.childElementCount ? '' : 'No matching Topics to add.'
      } catch {
        if (id === requestId) feedback.textContent = 'Could not load Topics. Try searching again.'
      }
    }, 180)
  }

  if (recovered?.topic_ids) {
    selected.clear()
    recovered.topic_ids.forEach(id => selected.add(id))
  } else {
    for (const option of form.elements.unassign_topics?.selectedOptions || []) {
      selected.delete(option.value)
    }
    for (const option of form.elements.assign_topics.selectedOptions) {
      assign(options.get(option.value))
    }
  }

  renderSelection()
  input.addEventListener('input', refresh)
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    suggestions.querySelector('button')?.click()
  })
  fieldset.querySelector('[data-topic-fallback]').hidden = true
  fieldset.querySelector('[data-topic-enhanced]').hidden = false
  return {
    initialIds: data.assigned,
    ids: () => [...selected].sort(),
    replace(topics, submittedIds = [...selected]) {
      // Preserve Topic edits made while the save was in flight.
      const removed = new Set(submittedIds.filter(id => !selected.has(id)))
      const added = [...selected].filter(id => !submittedIds.includes(id))
      selected.clear()
      for (const topic of topics) {
        options.set(topic.id, topic)
        if (!removed.has(topic.id)) selected.add(topic.id)
      }
      added.forEach(id => selected.add(id))
      if (renderSelection()) refresh()
    },
  }
}

export function notePayload(snapshot, assigned = []) {
  const { topic_ids: selected, ...payload } = JSON.parse(snapshot)
  if (selected) {
    const current = new Set(assigned)
    const next = new Set(selected)
    const changes = [
      ...assigned.filter(id => !next.has(id)).map(topic => ({ action: 'unassign', topic })),
      ...selected.filter(id => !current.has(id)).map(topic => ({ action: 'assign', topic })),
    ]
    if (changes.length) payload.topic_changes = changes
  }
  return payload
}
