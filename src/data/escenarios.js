// SOLUCION PROFESIONAL: NO hardcodear "/assets/..." (causa 404 con Railway Static + hash Vite).
// Importar assets COMO MODULOS VITE con sintaxis "?url" → Vite resuelve path + hash al buildear.
// Funciona 100% tanto en dev (localhost:5173) como en prod Railway Static (hash MD5 en nombre).
import _bgCristoRey from '../assets/esc-cristorey.jpg?url'
import _bgPlazaVarela from '../assets/esc-plazavarela.jpg?url'
import _bgMuseoSalsa from '../assets/esc-museosalsa.jpg?url'
import _btlFiesta from '../assets/botella-fiesta-azul.png?url'
import _btlNight from '../assets/botella-night.png?url'
import _btlSinAzucar from '../assets/botella-sin-azucar.png?url'

export const ESCENARIOS = [
  {
    id: 'calle-del-sabor',
    nombre: 'Museo de la Salsa',
    descripcion: 'Cuna de la salsa caleña. Historia y ritmo en cada pared.',
    gradiente: 'linear-gradient(135deg, #f97316 0%, #ea580c 35%, #b45309 100%)',
    acento: '#fb923c',
    icono: '🎶',
    tags: ['Salsa', 'Museo'],
    botellaImg: _btlFiesta,
    botellaNombre: 'Fiesta',
    backgroundImg: _bgMuseoSalsa,
    imagenPrompt: 'Museo de la Salsa en Santiago de Cali, ambiente cultural y festivo, fotografía profesional de alta calidad',
  },
  {
    id: 'plaza-varela',
    nombre: 'Plaza Varela',
    descripcion: 'El corazón de la salsa en Cali. Ritmo, cultura y vida callejera.',
    gradiente: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 35%, #4c1d95 100%)',
    acento: '#a78bfa',
    icono: '💃',
    tags: ['Salsa', 'Cultura'],
    botellaImg: _btlNight,
    botellaNombre: 'Night',
    backgroundImg: _bgPlazaVarela,
    imagenPrompt: 'Plaza Varela de Santiago de Cali al atardecer, fuente central, gente bailando salsa, fotografía de alta gama',
  },
  {
    id: 'cristo-rey',
    nombre: 'Cristo Rey',
    descripcion: 'La mejor vista panorámica 360° de toda Cali, desde lo más alto.',
    gradiente: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 35%, #075985 100%)',
    acento: '#38bdf8',
    icono: '⛰️',
    tags: ['Panorámica', 'Ícono'],
    botellaImg: _btlSinAzucar,
    botellaNombre: 'Sin Azúcar',
    backgroundImg: _bgCristoRey,
    imagenPrompt: 'Monumento del Cristo Rey de Santiago de Cali con vista panorámica de toda la ciudad, fotografía profesional 4k',
  },
]

export const ESCENARIO_MAP = ESCENARIOS.reduce((acc, e) => {
  acc[e.id] = e
  return acc
}, {})
