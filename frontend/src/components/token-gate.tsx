import type React from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";

interface TokenGateProps {
  onSubmit: (token: string) => void;
}

export function TokenGate({ onSubmit }: TokenGateProps): React.ReactElement {
  const [token, setToken] = useState("");

  return (
    <main className="token-page">
      <section className="token-card">
        <div className="brand-mark">C</div>
        <h1>需要管理密钥</h1>
        <p>输入 ADMIN_TOKEN 后进入控制台。关闭标签页后需要重新输入。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit(token.trim());
          }}
        >
          <label>
            <KeyRound size={18} />
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="ADMIN_TOKEN"
              autoFocus
            />
          </label>
          <button className="primary-button" type="submit" disabled={!token.trim()}>
            进入控制台
          </button>
        </form>
        <small>公网管理台仅接受 ADMIN_TOKEN，不再回退 API_TOKEN。</small>
      </section>
      <section className="token-preview" aria-hidden="true">
        <span>
          <ShieldCheck size={16} />
          实时任务预览
        </span>
        <strong>Queue Console</strong>
        <div className="preview-metrics">
          <div>
            <b>128</b>
            <span>总任务</span>
          </div>
          <div>
            <b>112</b>
            <span>成功</span>
          </div>
          <div>
            <b>1</b>
            <span>运行中</span>
          </div>
        </div>
        <ul>
          <li>
            <span>task_w3Pg75B4...</span>
            <b className="ok">成功 100%</b>
          </li>
          <li>
            <span>task_P7NboZ...</span>
            <b>运行中 63%</b>
          </li>
          <li>
            <span>task_Dk7oL0...</span>
            <b className="bad">失败</b>
          </li>
        </ul>
      </section>
    </main>
  );
}
