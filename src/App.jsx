import { Routes, Route, Navigate } from 'react-router-dom'
import { LegalDisclaimer } from './components/BrandComponents.jsx'
import Bienvenida from './screens/Bienvenida.jsx'
import Instrucciones from './screens/Instrucciones.jsx'
import Camara from './screens/Camara.jsx'
import SeleccionEscenario from './screens/SeleccionEscenario.jsx'
import Resultado from './screens/Resultado.jsx'
import Listo from './screens/Listo.jsx'
import LandingDescarga from './screens/LandingDescarga.jsx'
import './styles/brand.css'

export default function App() {
  return (
    <div className="app-container">
      <Routes>
        <Route path="/" element={<Bienvenida />} />
        <Route path="/instrucciones" element={<Instrucciones />} />
        <Route path="/camara" element={<Camara />} />
        <Route path="/escenario" element={<SeleccionEscenario />} />
        <Route path="/resultado" element={<Resultado />} />
        <Route path="/listo" element={<Listo />} />
        <Route path="/foto/:id" element={<LandingDescarga />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
