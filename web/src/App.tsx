import {
  Activity,
  Ban,
  CheckCircle2,
  Database,
  Film,
  KeyRound,
  ListFilter,
  Radio,
  RefreshCw,
  Save,
  Search,
  Send,
  Shield,
  TerminalSquare,
  Tv
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type Status = {
  worker: { running: boolean; can_start?: boolean; session_exists?: boolean };
  telegram: { configured: boolean; source_count: number; target_channel: string };
  tmdb: { configured: boolean; language: string };
  stats: Record<string, number>;
};

type RecordItem = {
  id: number;
  source_channel: string;
  title: string;
  tmdb_id: number | null;
  tmdb_media_type: string | null;
  tmdb_title: string | null;
  tmdb_year: number | null;
  region_category: string | null;
  genres: string[];
  decision: string;
  reason: string;
  created_at: string;
};

type SettingsPayload = {
  telegram: { source_channels: string[]; target_channel: string };
  filters: {
    blacklist_region_categories: string[];
    blacklist_genres: string[];
    blacklist_genre_ids: number[];
  };
};

type ActiveView = "overview" | "login" | "channels" | "filters" | "records";

const fallbackStatus: Status = {
  worker: { running: false },
  telegram: { configured: false, source_count: 0, target_channel: "" },
  tmdb: { configured: false, language: "zh-CN" },
  stats: { forwarded: 0, filtered: 0, failed: 0, pending: 0 }
};

const fallbackSettings: SettingsPayload = {
  telegram: { source_channels: [], target_channel: "" },
  filters: { blacklist_region_categories: [], blacklist_genres: [], blacklist_genre_ids: [] }
};

const decisionLabels: Record<string, string> = {
  forwarded: "已转发",
  filtered: "已过滤",
  failed: "失败",
  pending: "待处理"
};

const pageCopy: Record<ActiveView, { title: string; description: string }> = {
  overview: {
    title: "总览",
    description: "查看监听状态、今日转发过滤数量，并手动启动、停止或测试转发。"
  },
  login: {
    title: "Telegram 登录",
    description: "这里只处理 Telegram 登录，验证码和二步验证都在这一页完成。"
  },
  channels: {
    title: "频道设置",
    description: "配置源频道和目标频道，保存后运行中的监听服务会立即使用新配置。"
  },
  filters: {
    title: "黑名单",
    description: "配置分类、TMDB 类型和 Genre ID 黑名单，保存后立即生效。"
  },
  records: {
    title: "处理记录",
    description: "查看每条消息的 TMDB 识别、分类、过滤原因和转发结果。"
  }
};

export default function App() {
  const [status, setStatus] = useState<Status>(fallbackStatus);
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [settings, setSettings] = useState<SettingsPayload>(fallbackSettings);
  const [sourceChannelsText, setSourceChannelsText] = useState("");
  const [targetChannel, setTargetChannel] = useState("");
  const [blacklistRegionCategoriesText, setBlacklistRegionCategoriesText] = useState("");
  const [blacklistGenresText, setBlacklistGenresText] = useState("");
  const [blacklistGenreIdsText, setBlacklistGenreIdsText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [workerBusy, setWorkerBusy] = useState(false);
  const [refreshSeconds, setRefreshSeconds] = useState(30);
  const [activeView, setActiveView] = useState<ActiveView>("overview");
  const formInitialized = useRef(false);
  const formDirty = useRef(false);

  async function refresh() {
    setLoading(true);
    try {
      const [statusRes, recordsRes, settingsRes, loginRes] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/records?limit=100"),
        fetch("/api/settings"),
        fetch("/api/telegram-login")
      ]);
      const nextStatus = await statusRes.json();
      const nextSettings = await settingsRes.json();
      setStatus(nextStatus);
      setRecords((await recordsRes.json()).items ?? []);
      setSettings(nextSettings);
      if (!formInitialized.current || !formDirty.current) {
        syncForm(nextSettings);
        formInitialized.current = true;
      }
      const login = await loginRes.json();
      setLoginMessage(login.message || "");
    } finally {
      setLoading(false);
    }
  }

  function syncForm(nextSettings: SettingsPayload) {
    setSourceChannelsText(nextSettings.telegram.source_channels.join("\n"));
    setTargetChannel(nextSettings.telegram.target_channel);
    setBlacklistRegionCategoriesText(nextSettings.filters.blacklist_region_categories.join("\n"));
    setBlacklistGenresText(nextSettings.filters.blacklist_genres.join("\n"));
    setBlacklistGenreIdsText(nextSettings.filters.blacklist_genre_ids.join("\n"));
  }

  function markFormDirty() {
    formDirty.current = true;
    setNotice("有未保存修改，填完记得点“保存配置”。");
  }

  async function saveSettings() {
    setSaving(true);
    setNotice("");
    try {
      const payload: SettingsPayload = {
        telegram: {
          source_channels: lines(sourceChannelsText),
          target_channel: targetChannel.trim()
        },
        filters: {
          blacklist_region_categories: lines(blacklistRegionCategoriesText),
          blacklist_genres: lines(blacklistGenresText),
          blacklist_genre_ids: lines(blacklistGenreIdsText).map((item) => Number(item)).filter((item) => Number.isFinite(item))
        }
      };
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await response.text());
      const nextSettings = await response.json();
      setSettings(nextSettings);
      formDirty.current = false;
      formInitialized.current = true;
      syncForm(nextSettings);
      setNotice("配置已保存，正在运行的监听服务已立即生效。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function sendCode() {
    setLoginBusy(true);
    setLoginMessage("");
    try {
      const response = await fetch("/api/telegram-login/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone })
      });
      const payload = await response.json();
      setLoginMessage(payload.message || payload.detail || "验证码已发送，请查看 Telegram。");
    } catch (error) {
      setLoginMessage(error instanceof Error ? error.message : "发送验证码失败");
    } finally {
      setLoginBusy(false);
    }
  }

  async function signIn() {
    setLoginBusy(true);
    setLoginMessage("");
    try {
      const response = await fetch("/api/telegram-login/sign-in", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, password: password || null })
      });
      const payload = await response.json();
      setLoginMessage(payload.message || payload.detail || "登录完成。");
      formDirty.current = false;
      await refresh();
    } catch (error) {
      setLoginMessage(error instanceof Error ? error.message : "登录失败");
    } finally {
      setLoginBusy(false);
    }
  }

  useEffect(() => {
    refresh();
    if (refreshSeconds <= 0) return;
    const timer = window.setInterval(refresh, refreshSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [refreshSeconds]);

  async function workerAction(action: "start" | "stop" | "restart" | "test-forward") {
    setWorkerBusy(true);
    setNotice("");
    try {
      const response = await fetch(`/api/worker/${action}`, { method: "POST" });
      const payload = await response.json();
      setNotice(payload.message || "操作完成");
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "监听服务操作失败");
    } finally {
      setWorkerBusy(false);
    }
  }

  const filteredRecords = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return records;
    return records.filter((item) =>
      [item.title, item.tmdb_title, item.source_channel, item.reason, String(item.tmdb_id ?? "")]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(q))
    );
  }, [records, query]);

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <div className="brandMark"><Send size={20} aria-hidden="true" /></div>
          <div>
            <strong>TG Forwarder</strong>
            <span>TMDB 分类转发</span>
          </div>
        </div>
        <nav className="nav">
          <NavButton active={activeView === "overview"} icon={<Activity size={18} />} label="总览" onClick={() => setActiveView("overview")} />
          <NavButton active={activeView === "login"} icon={<KeyRound size={18} />} label="登录" onClick={() => setActiveView("login")} />
          <NavButton active={activeView === "channels"} icon={<Radio size={18} />} label="频道" onClick={() => setActiveView("channels")} />
          <NavButton active={activeView === "filters"} icon={<ListFilter size={18} />} label="黑名单" onClick={() => setActiveView("filters")} />
          <NavButton active={activeView === "records"} icon={<Database size={18} />} label="记录" onClick={() => setActiveView("records")} />
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{pageCopy[activeView].title}</h1>
            <p>{pageCopy[activeView].description}</p>
          </div>
          <button className="iconButton" type="button" onClick={refresh} aria-label="刷新状态">
            <RefreshCw size={18} aria-hidden="true" />
            <span>{loading ? "刷新中" : "刷新"}</span>
          </button>
        </header>

        {activeView === "overview" && (
          <>
            <section className="metrics" aria-label="服务状态">
              <Metric icon={<Radio />} label="监听服务" value={status.worker.running ? "运行中" : "未运行"} tone={status.worker.running ? "good" : "warn"} />
              <Metric icon={<Shield />} label="Telegram" value={status.telegram.configured ? "已配置" : "缺配置"} tone={status.telegram.configured ? "good" : "bad"} />
              <Metric icon={<Film />} label="TMDB" value={status.tmdb.configured ? status.tmdb.language : "缺配置"} tone={status.tmdb.configured ? "good" : "bad"} />
              <Metric icon={<CheckCircle2 />} label="今日转发" value={String(status.stats.forwarded ?? 0)} tone="info" />
              <Metric icon={<Ban />} label="今日过滤" value={String(status.stats.filtered ?? 0)} tone="warn" />
            </section>

            <section className="panel">
              <div className="panelHeader">
                <div>
                  <h2>监听控制</h2>
                  <p>登录成功并保存频道后，可以在这里启动、停止或测试转发。</p>
                </div>
                <Radio size={18} aria-hidden="true" />
              </div>
              <div className="formGrid three">
                <label className="control">
                  <span>自动刷新间隔</span>
                  <select value={refreshSeconds} onChange={(event) => setRefreshSeconds(Number(event.target.value))}>
                    <option value={0}>关闭自动刷新</option>
                    <option value={1800}>30 分钟</option>
                    <option value={3600}>1 小时</option>
                    <option value={7200}>2 小时</option>
                    <option value={10800}>3 小时</option>
                  </select>
                </label>
                <div className="statusField">
                  <span>登录 Session</span>
                  <div className="statusValue"><strong>{status.worker.session_exists ? "已保存" : "未登录"}</strong></div>
                </div>
                <div className="statusField">
                  <span>启动条件</span>
                  <div className="statusValue"><strong>{status.worker.can_start ? "可以启动" : "未满足"}</strong></div>
                </div>
              </div>
              <div className="actions">
                <button className="primaryButton" type="button" onClick={() => workerAction("start")} disabled={workerBusy}>启动监听</button>
                <button className="secondaryButton" type="button" onClick={() => workerAction("restart")} disabled={workerBusy}>重启监听</button>
                <button className="secondaryButton" type="button" onClick={() => workerAction("test-forward")} disabled={workerBusy}>立即测试转发</button>
                <button className="secondaryButton" type="button" onClick={() => workerAction("stop")} disabled={workerBusy}>停止监听</button>
              </div>
            </section>
          </>
        )}

        {activeView === "login" && (
          <section className="panel">
            <div className="panelHeader">
              <div>
                <h2>Telegram 登录</h2>
                <p>先输入手机号发送验证码，再填 Telegram 收到的验证码登录。如果开了二步验证，再填二步验证密码。</p>
              </div>
              <KeyRound size={18} aria-hidden="true" />
            </div>
            <div className="formGrid three">
              <label className="control">
                <span>手机号</span>
                <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+8613800000000" />
              </label>
              <label className="control">
                <span>验证码</span>
                <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="Telegram 发来的验证码" />
              </label>
              <label className="control">
                <span>二步验证密码</span>
                <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="没有就留空" />
              </label>
            </div>
            <div className="actions">
              <button className="primaryButton" type="button" onClick={sendCode} disabled={loginBusy || !phone.trim()}>发送验证码</button>
              <button className="secondaryButton" type="button" onClick={signIn} disabled={loginBusy || !code.trim()}>确认登录</button>
              {loginMessage && <span className="notice">{loginMessage}</span>}
            </div>
          </section>
        )}

        {activeView === "channels" && (
          <>
          <Panel title="频道设置" icon={<Radio />}>
            <label className="control">
              <span>源频道，一行一个</span>
              <textarea
                value={sourceChannelsText}
                onChange={(event) => {
                  markFormDirty();
                  setSourceChannelsText(event.target.value);
                }}
                rows={5}
                placeholder="@source_channel&#10;-1001234567890"
              />
            </label>
            <label className="control">
              <span>目标频道</span>
              <input
                value={targetChannel}
                onChange={(event) => {
                  markFormDirty();
                  setTargetChannel(event.target.value);
                }}
                placeholder="@target_channel"
              />
            </label>
          </Panel>
          <SaveBar saving={saving} notice={notice} onSave={saveSettings} />
          </>
        )}

        {activeView === "filters" && (
          <>
          <Panel title="TMDB 黑名单" icon={<ListFilter />}>
            <label className="control">
              <span>分类黑名单，一行一个</span>
              <textarea
                value={blacklistRegionCategoriesText}
                onChange={(event) => {
                  markFormDirty();
                  setBlacklistRegionCategoriesText(event.target.value);
                }}
                rows={5}
                placeholder="国产剧&#10;欧美剧&#10;国漫&#10;综艺"
              />
            </label>
            <label className="control">
              <span>TMDB 类型黑名单，一行一个</span>
              <textarea
                value={blacklistGenresText}
                onChange={(event) => {
                  markFormDirty();
                  setBlacklistGenresText(event.target.value);
                }}
                rows={4}
                placeholder="剧情&#10;犯罪&#10;真人秀"
              />
            </label>
            <label className="control">
              <span>Genre ID，一行一个</span>
              <textarea
                value={blacklistGenreIdsText}
                onChange={(event) => {
                  markFormDirty();
                  setBlacklistGenreIdsText(event.target.value);
                }}
                rows={4}
                placeholder="27&#10;99"
              />
            </label>
          </Panel>
          <SaveBar saving={saving} notice={notice} onSave={saveSettings} />
          </>
        )}

        {activeView === "records" && (
        <>
        <section className="panel tablePanel">
          <div className="panelHeader">
            <div>
              <h2>处理记录</h2>
              <p>这里会显示每条消息的 TMDB 识别、黑名单过滤和转发结果。</p>
            </div>
            <label className="searchBox">
              <Search size={16} aria-hidden="true" />
              <span className="srOnly">搜索记录</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、频道、TMDB ID" />
            </label>
          </div>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>状态</th>
                  <th>标题</th>
                  <th>TMDB</th>
                  <th>分类</th>
                  <th>来源</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>
                {filteredRecords.length ? (
                  filteredRecords.map((item) => (
                    <tr key={item.id}>
                      <td><Decision value={item.decision} /></td>
                      <td>
                        <strong>{item.tmdb_title || item.title}</strong>
                        <span>{item.tmdb_year || "年份未知"}</span>
                      </td>
                      <td className="mono">{item.tmdb_media_type && item.tmdb_id ? `${item.tmdb_media_type}/${item.tmdb_id}` : "-"}</td>
                      <td>
                        <PillList
                          values={[item.region_category, ...item.genres].filter(Boolean) as string[]}
                          empty="-"
                        />
                      </td>
                      <td>{item.source_channel}</td>
                      <td>{item.reason}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="emptyTable">暂无记录。登录并开始监听后，处理过的频道消息会出现在这里。</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel logs">
          <div className="panelHeader">
            <div>
              <h2>最近动态</h2>
              <p>从最新处理记录里汇总出来的简短流水。</p>
            </div>
            <TerminalSquare size={18} aria-hidden="true" />
          </div>
          <div className="logList">
            {records.slice(0, 8).map((item) => (
              <div className="logLine" key={`log-${item.id}`}>
                <span className="mono">{new Date(item.created_at).toLocaleString()}</span>
                <Decision value={item.decision} />
                <span>{item.title}</span>
              </div>
            ))}
            {!records.length && <div className="emptyLine">暂无动态。</div>}
          </div>
        </section>
        </>
        )}
      </section>
    </main>
  );
}

function lines(value: string) {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function Metric({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) {
  return (
    <article className={`metric ${tone}`}>
      <div className="metricIcon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={`navButton ${active ? "active" : ""}`} type="button" onClick={onClick} aria-current={active ? "page" : undefined}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div><h2>{title}</h2></div>
        {icon}
      </div>
      {children}
    </section>
  );
}

function SaveBar({ saving, notice, onSave }: { saving: boolean; notice: string; onSave: () => void }) {
  return (
    <div className="stickyActions">
      <button className="primaryButton" type="button" onClick={onSave} disabled={saving}>
        <Save size={17} aria-hidden="true" />
        {saving ? "保存中" : "保存配置"}
      </button>
      {notice && <span className="notice">{notice}</span>}
    </div>
  );
}

function PillList({ values, empty }: { values: string[]; empty: string }) {
  if (!values.length) return <span className="emptyLine">{empty}</span>;
  return (
    <span className="pillRow">
      {values.map((value) => <span className="pill" key={value}>{value}</span>)}
    </span>
  );
}

function Decision({ value }: { value: string }) {
  const icon = value === "forwarded" ? <CheckCircle2 size={14} /> : value === "filtered" ? <Ban size={14} /> : <Tv size={14} />;
  return <span className={`decision ${value}`}>{icon}{decisionLabels[value] ?? value}</span>;
}
