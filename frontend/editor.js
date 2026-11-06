import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { Link } from '@tiptap/extension-link'
import { OrderedList } from '@tiptap/extension-list'
import { autosave } from './autosave'

const form = document.querySelector('[data-note-editor]')
if (form) initializeEditor(form)

function websiteAddress(value) {
  if (!/^https?:\/\//i.test(value) || /[\s\x00-\x1f\x7f\\]/u.test(value) || value.length > 2048) return false
  try {
    const url = new URL(value)
    return Boolean(url.hostname) && url.port !== '0'
  } catch {
    return false
  }
}

function initializeEditor(form) {
  const plain = form.querySelector('[name="content"]')
  const source = form.querySelector('[name="content_document"]')
  const recovery = document.querySelector('#document-recovery')
  const message = document.querySelector('#editor-error')
  const toolbar = document.querySelector('#formatting-tools')
  const host = document.querySelector('#editor-host')
  let editor
  let changed = () => {}
  try {
    if (form.dataset.rejected === 'true') throw new Error('Rejected document')
    const stored = source.value ? JSON.parse(source.value) : { format: 'plain-text', text: plain.value }
    const content = stored.format === 'tiptap' ? stored.doc : {
      type: 'doc',
      content: stored.text.split('\n').map(text => ({
        type: 'paragraph',
        ...(text ? { content: [{ type: 'text', text }] } : {}),
      })),
    }
    // Only href is part of the Note contract; presentation attributes stay in HTML.
    const NoteLink = Link.extend({
      addAttributes() { return { href: this.parent().href } },
    })
    const NoteOrderedList = OrderedList.extend({
      addAttributes() { return { start: this.parent().start } },
    })
    editor = new Editor({
      element: host,
      enableContentCheck: true,
      extensions: [
        StarterKit.configure({
          heading: false, code: false, codeBlock: false, strike: false,
          underline: false, horizontalRule: false, link: false, orderedList: false,
          trailingNode: false,
        }),
        NoteOrderedList,
        NoteLink.configure({
          openOnClick: false, defaultProtocol: 'https',
          isAllowedUri: websiteAddress,
          HTMLAttributes: { target: null, rel: 'noopener noreferrer' },
        }),
      ],
      content,
      editorProps: {
        attributes: {
          id: 'note-editor', role: 'textbox', 'aria-label': 'Your note',
          'aria-multiline': 'true', 'aria-describedby': 'content-help',
        },
      },
      onUpdate: sync,
      onSelectionUpdate: updateToolbar,
      onTransaction: updateToolbar,
    })
  } catch {
    message.textContent = 'The formatted draft could not be loaded. Its original JSON is retained below; correct it before saving.'
    message.hidden = false
    recovery.open = true
    document.querySelector('#note-content-label').htmlFor = 'id_content'
    return
  }

  function sync() {
    // On initialization Editor has not yet returned; wait for the explicit sync below.
    if (!editor) return
    source.value = JSON.stringify({ version: 1, format: 'tiptap', doc: editor.getJSON() })
    plain.value = editor.getText({ blockSeparator: '\n' })
    changed()
  }
  const commands = {
    bold: () => editor.chain().focus().toggleBold().run(),
    italic: () => editor.chain().focus().toggleItalic().run(),
    paragraph: () => editor.chain().focus().setParagraph().run(),
    blockquote: () => editor.chain().focus().toggleBlockquote().run(),
    bulletList: () => editor.chain().focus().toggleBulletList().run(),
    orderedList: () => editor.chain().focus().toggleOrderedList().run(),
    undo: () => editor.chain().focus().undo().run(),
    redo: () => editor.chain().focus().redo().run(),
  }
  function updateToolbar() {
    if (!editor) return
    toolbar.querySelectorAll('[data-format]').forEach(button => {
      button.setAttribute('aria-pressed', String(editor.isActive(button.dataset.format)))
    })
  }
  toolbar.querySelectorAll('[data-command]').forEach(button => {
    button.addEventListener('click', () => commands[button.dataset.command]())
  })
  const dialog = document.querySelector('#link-dialog')
  const address = dialog.querySelector('input')
  const linkError = dialog.querySelector('[role="alert"]')
  document.querySelector('#website-link').addEventListener('click', () => {
    address.value = editor.getAttributes('link').href || ''
    linkError.hidden = true
    dialog.showModal()
    address.focus()
  })
  dialog.querySelector('form').addEventListener('submit', event => {
    event.preventDefault()
    if (!websiteAddress(address.value)) {
      linkError.hidden = false
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: address.value }).run()
    dialog.close()
  })
  dialog.querySelector('[data-remove-link]').addEventListener('click', () => {
    editor.chain().focus().extendMarkRange('link').unsetLink().run()
    dialog.close()
  })
  dialog.querySelector('[data-cancel-link]').addEventListener('click', () => {
    dialog.close()
    editor.commands.focus()
  })
  let saving = false
  if (!form.querySelector('[name="revision"]')) form.addEventListener('submit', async event => {
    event.preventDefault()
    if (saving) return
    sync()
    const payload = {
      content: JSON.parse(source.value),
      book: form.querySelector('[name="book"]').value || null,
    }
    const controls = form.querySelectorAll('button, select')
    const status = document.querySelector('#save-status')
    const another = event.submitter?.name === 'add_another'
    saving = true
    let confirmed = false
    controls.forEach(control => { control.disabled = true })
    editor.setEditable(false)
    status.textContent = 'Saving…'
    message.hidden = true
    try {
      const response = await fetch(form.dataset.apiUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
        },
        body: JSON.stringify(payload),
      })
      const result = await response.json()
      if (!response.ok) {
        message.textContent = result.error.message
        message.hidden = false
        status.textContent = response.status === 409 ? 'Conflict. Your draft is still here.' : 'Not saved. Your draft is still here.'
        return
      }
      confirmed = true
      status.textContent = 'Saved.'
      window.location.assign(another
        ? (result.book ? `/books/${result.book}/notes/new/` : '/notes/new/')
        : `/notes/${result.id}/`)
    } catch {
      message.textContent = 'Could not confirm saving. Your draft is still here. Check your connection and saved Notes before retrying.'
      message.hidden = false
      status.textContent = 'Save not confirmed.'
    } finally {
      if (!confirmed) {
        saving = false
        controls.forEach(control => { control.disabled = false })
        editor.setEditable(true)
      }
    }
  })
  plain.hidden = true
  plain.removeAttribute('autofocus')
  recovery.hidden = true
  host.hidden = false
  toolbar.hidden = false
  sync()
  if (form.querySelector('[name="revision"]')) changed = autosave(form)
  updateToolbar()
  editor.commands.focus('end')
}
