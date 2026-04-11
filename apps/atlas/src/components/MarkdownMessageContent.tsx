import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownMessageContentProps = {
  content: string;
};

const MarkdownCodeBlock = lazy(async () => {
  const module = await import("./MarkdownCodeBlock");
  return { default: module.MarkdownCodeBlock };
});

export function MarkdownMessageContent({ content }: MarkdownMessageContentProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const raw = String(children).replace(/\n$/, "");
          const match = /language-(\w+)/.exec(className || "");
          if (!match) {
            return (
              <code className="inline-code" {...props}>
                {children}
              </code>
            );
          }
          return (
            <Suspense fallback={<StaticCodeBlock code={raw} />}>
              <MarkdownCodeBlock code={raw} language={match[1]} />
            </Suspense>
          );
        },
        pre({ children }) {
          return <>{children}</>;
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function StaticCodeBlock({ code }: { code: string }) {
  return (
    <div className="code-block-shell">
      <div className="code-block-header">
        <span>code</span>
      </div>
      <div className="code-block-code" style={{ padding: "14px 16px", whiteSpace: "pre-wrap" }}>
        {code}
      </div>
    </div>
  );
}
