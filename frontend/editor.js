import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { Link } from '@tiptap/extension-link'
import { OrderedList } from '@tiptap/extension-list'
import { autosave } from './autosave'
import { explicitCapture } from './capture'
import { noteChapters } from './chapters'
import { noteDraft, noteSourceInputs } from './drafts'

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
  const book = form.querySelector('[name="book"]')
  const draft = noteDraft(form)
  const syncChapter = noteChapters(form)
  const initialBook = book.value || null
  let editor
  let changed = () => {}
  try {
    if (form.dataset.rejected === 'true') throw new Error('Rejected document')
    const recovered = draft.recovered && JSON.parse(draft.recovered.snapshot)
    const stored = recovered?.content || (source.value
      ? JSON.parse(source.value)
      : { format: 'plain-text', text: plain.value })
    if (recovered) {
      source.value = JSON.stringify(stored)
      for (const input of noteSourceInputs(form)) {
        if (input.name === 'chapter') syncChapter(recovered.chapter)
        if (input.name in recovered) input.value = recovered[input.name] ?? ''
      }
    }
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
    if (draft.recovered) {
      // A native submit would skip acknowledgement of the local draft and
      // could send a recovered edit with the current server revision.
      form.querySelectorAll('[data-explicit-save], [name="add_another"]').forEach(button => {
        button.disabled = true
      })
      form.addEventListener('submit', event => event.preventDefault())
      message.textContent = 'The local draft could not be loaded. Reload to try again, or copy its original JSON below.'
    } else {
      message.textContent = 'The formatted draft could not be loaded. Its original JSON is retained below. Correct it before saving.'
    }
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
  plain.hidden = true
  plain.removeAttribute('autofocus')
  recovery.hidden = true
  host.hidden = false
  toolbar.hidden = false
  sync()
  if (form.querySelector('[name="revision"]')) changed = autosave(form, draft)
  else changed = explicitCapture(form, editor, draft, initialBook)
  updateToolbar()
  editor.commands.focus('end')
}
