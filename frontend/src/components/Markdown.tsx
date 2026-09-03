import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Shared renderer for model-generated text (K2 step output, final answers).
 * `dir="auto"` on the wrapper lets the browser pick LTR/RTL per block from
 * the actual Unicode content, independent of the page's global language
 * toggle -- an English question can get an Arabic-leaning answer (or a
 * mixed one) and each still reads correctly.
 */
export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div dir="auto" className={`markdown-body ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2 leading-relaxed last:mb-0">{children}</p>,
          h1: ({ children }) => <h3 className="mb-2 mt-3 text-sm font-bold text-gcc-navy first:mt-0">{children}</h3>,
          h2: ({ children }) => <h3 className="mb-2 mt-3 text-sm font-bold text-gcc-navy first:mt-0">{children}</h3>,
          h3: ({ children }) => (
            <h4 className="mb-1.5 mt-3 text-xs font-bold uppercase tracking-wide text-gcc-navy/80 first:mt-0">
              {children}
            </h4>
          ),
          strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
          em: ({ children }) => <em className="text-slate-700">{children}</em>,
          ul: ({ children }) => <ul className="mb-2 ms-4 list-disc space-y-1 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-2 ms-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          hr: () => <hr className="my-3 border-slate-200" />,
          code: ({ children }) => (
            <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-s-2 border-gcc-gold/60 ps-3 text-slate-600">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-slate-200 px-2 py-1.5 text-start font-semibold text-slate-700">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="border-b border-slate-100 px-2 py-1.5 align-top">{children}</td>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-gcc-navy underline hover:text-gcc-teal">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
