function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(text: string) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function isMarkdownTableLine(line: string) {
  const text = line.trim()
  return text.startsWith('|') && text.endsWith('|') && text.split('|').length >= 3
}

function isMarkdownTableSeparator(line: string) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim())
}

function splitMarkdownTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function renderMarkdownTable(lines: string[]) {
  const rows = lines.filter((line) => isMarkdownTableLine(line) && !isMarkdownTableSeparator(line))
  if (!rows.length) return ''
  const header = splitMarkdownTableRow(rows[0])
  const body = rows.slice(1).map(splitMarkdownTableRow)
  const th = header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')
  const trs = body
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`)
    .join('')
  return `<div class="markdown-table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`
}

export function renderMarkdownReport(markdown: string) {
  const lines = (markdown || '').replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let listOpen = false

  const closeList = () => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (!line) {
      closeList()
      continue
    }
    if (isMarkdownTableLine(line)) {
      closeList()
      const tableLines: string[] = []
      for (; i < lines.length; i += 1) {
        const next = lines[i].trim()
        const nextNonEmpty = lines.slice(i + 1).find((candidate) => candidate.trim())
        if (!next && nextNonEmpty && isMarkdownTableLine(nextNonEmpty.trim())) continue
        if (isMarkdownTableLine(next)) {
          tableLines.push(next)
          continue
        }
        i -= 1
        break
      }
      html.push(renderMarkdownTable(tableLines))
      continue
    }
    if (/^-{3,}$/.test(line)) {
      closeList()
      html.push('<hr>')
      continue
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 2, 5)
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line)
    if (bullet) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderInlineMarkdown(bullet[1])}</li>`)
      continue
    }
    closeList()
    html.push(`<p>${renderInlineMarkdown(line)}</p>`)
  }

  closeList()
  return html.join('')
}
