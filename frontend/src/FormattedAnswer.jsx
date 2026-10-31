import { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

function renderMathInText(text) {
  if (!text) return ''

  // 1. Process display math blocks: $$ ... $$
  let processed = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    try {
      return `<div class="math-block">${katex.renderToString(math.trim(), { displayMode: true, throwOnError: false })}</div>`
    } catch {
      return `<div class="math-block">${math}</div>`
    }
  })

  // 2. Process inline math: $ ... $ (excluding escaped \$)
  processed = processed.replace(/(?<!\\)\$([^\$\n]+?)\$/g, (_, math) => {
    try {
      return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false })
    } catch {
      return `$${math}$`
    }
  })

  return processed
}

function renderMarkdownLine(line) {
  // Bold: **text**
  let s = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  // Inline code: `text`
  s = s.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  // Math in line
  s = renderMathInText(s)
  return s
}

export default function FormattedAnswer({ content }) {
  const html = useMemo(() => {
    if (!content) return ''

    // First handle multiline $$ ... $$ blocks if any
    const mathReplaced = content.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
      try {
        return `\n<div class="math-block">${katex.renderToString(math.trim(), { displayMode: true, throwOnError: false })}</div>\n`
      } catch {
        return `\n<div class="math-block">${math}</div>\n`
      }
    })

    const lines = mathReplaced.split('\n')
    const out = []
    let inList = false

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim()

      if (!line) {
        if (inList) {
          out.push('</ul>')
          inList = false
        }
        continue
      }

      // If it's already a div block from display math
      if (line.startsWith('<div class="math-block">')) {
        if (inList) {
          out.push('</ul>')
          inList = false
        }
        out.push(line)
        continue
      }

      // Headings
      if (line.startsWith('### ')) {
        if (inList) { out.push('</ul>'); inList = false }
        out.push(`<h4>${renderMarkdownLine(line.slice(4))}</h4>`)
        continue
      }
      if (line.startsWith('## ')) {
        if (inList) { out.push('</ul>'); inList = false }
        out.push(`<h3>${renderMarkdownLine(line.slice(3))}</h3>`)
        continue
      }
      if (line.startsWith('# ')) {
        if (inList) { out.push('</ul>'); inList = false }
        out.push(`<h2>${renderMarkdownLine(line.slice(2))}</h2>`)
        continue
      }

      // Bullet items: * or -
      const bulletMatch = line.match(/^[\*\-]\s+(.*)$/)
      if (bulletMatch) {
        if (!inList) {
          out.push('<ul class="md-list">')
          inList = true
        }
        out.push(`<li>${renderMarkdownLine(bulletMatch[1])}</li>`)
        continue
      }

      // Numbered items: 1. or 2.
      const numMatch = line.match(/^\d+\.\s+(.*)$/)
      if (numMatch) {
        if (inList) { out.push('</ul>'); inList = false }
        out.push(`<div class="num-item">${renderMarkdownLine(line)}</div>`)
        continue
      }

      // Regular paragraph
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      out.push(`<p>${renderMarkdownLine(line)}</p>`)
    }

    if (inList) {
      out.push('</ul>')
    }

    return out.join('\n')
  }, [content])

  return (
    <div
      className="formatted-answer"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
