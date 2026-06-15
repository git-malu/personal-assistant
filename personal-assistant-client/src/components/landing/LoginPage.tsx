import { useMsal } from "@azure/msal-react";
import { loginRequest } from "@/lib/auth";
import { ArrowLeft } from "lucide-react";

interface LoginPageProps {
  onBack: () => void;
}

function MicrosoftIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" className="shrink-0">
      <rect x="1" y="1" width="10" height="10" fill="#f25022" rx="1.5" />
      <rect x="13" y="1" width="10" height="10" fill="#7fba00" rx="1.5" />
      <rect x="1" y="13" width="10" height="10" fill="#00a4ef" rx="1.5" />
      <rect x="13" y="13" width="10" height="10" fill="#ffb900" rx="1.5" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" className="shrink-0" fill="#1d1d1f">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
    </svg>
  );
}

function WeChatIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" className="shrink-0" fill="#00c800">
      <path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 01.213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 00.167-.054l1.903-1.114a.864.864 0 01.717-.098 10.16 10.16 0 002.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 01-1.162 1.178A1.17 1.17 0 014.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 01-1.162 1.178 1.17 1.17 0 01-1.162-1.178c0-.651.52-1.18 1.162-1.18zm3.91 3.508c-2.476 0-4.492 2.053-4.492 4.576 0 1.442.67 2.777 1.816 3.654a.44.44 0 01.155.497l-.286 1.1a.222.222 0 00.338.236l1.414-.828a.655.655 0 01.542-.073c.985.326 1.99.327 2.498.327 2.476 0 4.492-2.053 4.492-4.577 0-2.523-2.016-4.576-4.492-4.576-.646 0-1.098.05-1.643.17a4.861 4.861 0 00-.898.005zm-2.162 2.359c.486 0 .88.4.88.892a.886.886 0 01-.88.891.886.886 0 01-.88-.891c0-.492.394-.892.88-.892zm4.326 0c.487 0 .88.4.88.892a.886.886 0 01-.88.891.886.886 0 01-.88-.891c0-.492.394-.892.88-.892z"/>
    </svg>
  );
}

export function LoginPage({ onBack }: LoginPageProps) {
  const { instance } = useMsal();

  const handleMicrosoftLogin = () => {
    instance.loginRedirect(loginRequest);
  };

  return (
    <div className="min-h-dvh bg-white flex flex-col">
      <div className="h-[44px] flex items-center px-5">
        <button onClick={onBack} className="flex items-center gap-1 text-[#0066cc] text-[15px] hover:opacity-80">
          <ArrowLeft className="w-4 h-4" />
          返回
        </button>
      </div>
      
      <div className="flex-1 flex items-center justify-center px-8">
        <div className="max-w-[420px] w-full">
          <h2 className="text-[28px] font-semibold text-center mb-2">登录 Personal Assistant</h2>
          <p className="text-[15px] text-[#7a7a7a] text-center mb-10">选择一种方式登录您的账号</p>
          
          <button onClick={handleMicrosoftLogin} className="w-full flex items-center gap-4 p-5 rounded-xl border border-[#e0e0e0] hover:bg-[#f5f5f7] transition-colors mb-3">
            <MicrosoftIcon />
            <div className="text-left flex-1">
              <span className="text-[17px] font-medium text-[#1d1d1f]">Microsoft 账号</span>
              <p className="text-[13px] text-[#7a7a7a]">使用 Entra ID 或 Microsoft 365 账号</p>
            </div>
          </button>
          
          <div className="w-full flex items-center gap-4 p-5 rounded-xl border border-[#e0e0e0] opacity-50 cursor-not-allowed mb-3">
            <GitHubIcon />
            <div className="text-left flex-1">
              <span className="text-[17px] font-medium text-[#1d1d1f]">GitHub 账号</span>
              <p className="text-[13px] text-[#7a7a7a]">使用 GitHub 账号登录</p>
            </div>
            <span className="text-[12px] text-[#7a7a7a] bg-[#f5f5f7] px-2 py-0.5 rounded-full whitespace-nowrap">即将支持</span>
          </div>
          
          <div className="w-full flex items-center gap-4 p-5 rounded-xl border border-[#e0e0e0] opacity-50 cursor-not-allowed">
            <WeChatIcon />
            <div className="text-left flex-1">
              <span className="text-[17px] font-medium text-[#1d1d1f]">微信账号</span>
              <p className="text-[13px] text-[#7a7a7a]">使用微信扫码登录</p>
            </div>
            <span className="text-[12px] text-[#7a7a7a] bg-[#f5f5f7] px-2 py-0.5 rounded-full whitespace-nowrap">即将支持</span>
          </div>
        </div>
      </div>
      
      <div className="text-center pb-8">
        <p className="text-[12px] text-[#7a7a7a]">Personal Assistant</p>
      </div>
    </div>
  );
}
