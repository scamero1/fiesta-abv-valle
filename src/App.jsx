import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { LegalDisclaimer } from './components/BrandComponents.jsx'
// 🏠 Home Bienvenida se carga SIN lazy (rápido — UX).
import Bienvenida from './screens/Bienvenida.jsx'
import LandingDescarga from './screens/LandingDescarga.jsx'
import './styles/brand.css'

// ⚡ Code Splitting React.lazy GLOBAL: TODAS pantallas flujo (no home) en CHUNKS separados.
// Reducción main bundle index.js ~ 25-30 kB → JS ≤ 227 kB límite GPU TCL Tab 10L.
// → ~ 150 kB inicial vs 229 kB = PWA carga 35% más rápido en móviles.
const Instrucciones = lazy(() => import('./screens/Instrucciones.jsx'))
const Camara = lazy(() => import('./screens/Camara.jsx'))
const SeleccionEscenario = lazy(() => import('./screens/SeleccionEscenario.jsx'))
const ConfirmarVistaPrevia = lazy(() => import('./screens/ConfirmarVistaPrevia.jsx'))
const Resultado = lazy(() => import('./screens/Resultado.jsx'))
const Listo = lazy(() => import('./screens/Listo.jsx'))

// 🔐 Promoción/Admin — lazy igual.
const Ganador = lazy(() => import('./screens/Ganador.jsx'))
const RegistroGanador = lazy(() => import('./screens/RegistroGanador.jsx'))
const AgradecimientoGanador = lazy(() => import('./screens/AgradecimientoGanador.jsx'))
const AdminLogin = lazy(() => import('./screens/AdminLogin.jsx'))
const AdminDashboard = lazy(() => import('./screens/AdminDashboard.jsx'))

function PromocionSuspenseFallback() {
  // Loading 8px azul + 256ms mínimo. Sin FOUC al navegar /ganador o /admin.
  return (
    <div className="screen" style={{ background: '#002a7a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 44, height: 44, borderRadius: '50%', border: '4px solid rgba(255,255,255,.25)', borderTopColor: '#fff', animation: 'spin 0.9s linear infinite' }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

export default function App() {
  return (
    <div className="app-container">
      <Suspense fallback={<PromocionSuspenseFallback />}>
        <Routes>
          <Route path="/" element={<Bienvenida />} />
          <Route path="/instrucciones" element={<Instrucciones />} />
          <Route path="/camara" element={<Camara />} />
          <Route path="/escenario" element={<SeleccionEscenario />} />
          <Route path="/preview" element={<ConfirmarVistaPrevia />} />
          <Route path="/resultado" element={<Resultado />} />
          <Route path="/listo" element={<Listo />} />
          <Route path="/ganador" element={<Ganador />} />
          <Route path="/ganador/registro" element={<RegistroGanador />} />
          <Route path="/ganador/gracias/:id" element={<AgradecimientoGanador />} />
          <Route path="/admin" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/foto/:id" element={<LandingDescarga />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
