(() => {
  const editor = document.getElementById('body-editor');
  if (!editor) return;
  const replaceSelection = (before, after = before) => {
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selected = editor.value.slice(start, end);
    editor.setRangeText(`${before}${selected}${after}`, start, end, 'select');
    editor.focus();
  };
  document.querySelectorAll('.editor-toolbar button').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.dataset.wrap) replaceSelection(button.dataset.wrap);
      if (button.dataset.prefix) {
        const start = editor.selectionStart;
        const lineStart = editor.value.lastIndexOf('\n', start - 1) + 1;
        editor.setRangeText(button.dataset.prefix, lineStart, lineStart, 'end');
        editor.focus();
      }
      if (button.dataset.link) {
        const url = window.prompt('Paste the link URL');
        if (url) replaceSelection('[', `](${url})`);
      }
    });
  });
})();