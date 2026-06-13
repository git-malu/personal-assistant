export function LandingFooter() {
  return (
    <footer className="rounded-none bg-canvas-parchment py-[64px]">
      <div className="max-w-[980px] mx-auto text-[12px] text-[#333333]">
        <div className="mb-4">
          <p className="font-semibold">Personal Assistant</p>
          <p className="mt-1">
            基于 AI 的个人助理，用自然语言管理日程、邮件、笔记和任务。
          </p>
        </div>
        <div className="flex gap-6 mb-6">
          <span>文档</span>
          <span>隐私</span>
          <span>条款</span>
        </div>
        <p>Copyright © {new Date().getFullYear()} Personal Assistant. All rights reserved.</p>
      </div>
    </footer>
  );
}
