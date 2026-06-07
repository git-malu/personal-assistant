import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'

const rehypePlugins = [rehypeHighlight]

interface StreamingTextProps {
  text: string;
  isStreaming: boolean;
}

export const StreamingText = memo(function StreamingText({
  text,
  isStreaming,
}: StreamingTextProps) {
  if (!isStreaming) {
    return <ReactMarkdown rehypePlugins={rehypePlugins}>{text}</ReactMarkdown>
  }

  return (
    <>
      <ReactMarkdown rehypePlugins={rehypePlugins}>{text}</ReactMarkdown>
      <span className="cursor-blink" />
    </>
  )
})
