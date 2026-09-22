import { lazy, Suspense } from 'react'
import { NavLink, Route, Routes, useSearchParams } from 'react-router-dom'
import { Button, Loading } from './components'
import { SnapshotProvider, snapshotHref, useSnapshot } from './snapshot-context'
import './styles.css'

const OverviewPage = lazy(() => import('./pages/OverviewPage'))
const ExperimentsPage = lazy(() => import('./pages/ExperimentsPage'))
const ExperimentDetailPage = lazy(() => import('./pages/ExperimentDetailPage'))
const ComparePage = lazy(() => import('./pages/ComparePage'))
const SignalsPage = lazy(() => import('./pages/SignalsPage'))
const ProspectivePage = lazy(() => import('./pages/ProspectivePage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))

export default function App() {
  return <SnapshotProvider><Shell /></SnapshotProvider>
}

function Shell() {
  const { snapshotId, current, pinnedIsCurrent } = useSnapshot()
  const [params, setParams] = useSearchParams()
  const links = [
    ['/', '总览'],
    ['/experiments', '实验中心'],
    ['/signals', '信号诊断'],
    ['/prospective', '前瞻模拟'],
    ['/health', '数据与系统健康'],
  ]
  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><span>Quant Console</span><small>V1.5</small></div>
      <nav>{links.map(([to, label]) => <NavLink key={to} to={snapshotHref(to, snapshotId)} end={to === '/'}>{label}</NavLink>)}</nav>
      <div className="snapshot-card">
        {current?.mode === 'demo' && <strong className="demo-banner">演示数据，不是研究结果</strong>}
        <span>展示快照</span><code>{snapshotId.slice(0, 12)}</code>
        <small>{pinnedIsCurrent ? '当前发布版本' : '固定查看旧版本'}</small>
      </div>
    </aside>
    <div className="content">
      {!pinnedIsCurrent && current && <div className="new-snapshot-banner">
        <span>已有新快照 {current.snapshot_id.slice(0, 12)}，当前页面仍保持旧版本一致性。</span>
        <Button variant="secondary" onClick={() => {
          const next = new URLSearchParams(params)
          next.set('snapshot', current.snapshot_id)
          setParams(next)
        }}>切换到当前快照</Button>
      </div>}
      <Suspense fallback={<Loading label="正在加载页面组件…" />}>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/experiments/compare" element={<ComparePage />} />
          <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/prospective" element={<ProspectivePage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="*" element={<main><h1>页面不存在</h1><NavLink to={snapshotHref('/', snapshotId)}>返回总览</NavLink></main>} />
        </Routes>
      </Suspense>
    </div>
  </div>
}
