export const ESCENARIOS = [
  {
    id: 'calle-del-sabor',
    nombre: 'Museo de la Salsa',
    descripcion: 'El templo de la salsa caleña, donde la historia y el ritmo de la música más colombiana se vive en cada pared.',
    gradiente: 'linear-gradient(135deg, #f97316 0%, #ea580c 35%, #b45309 100%)',
    acento: '#fb923c',
    icono: '🎶',
    tags: ['Salsa', 'Museo'],
    botellaImg: '/assets/botella-fiesta-azul.png',
    botellaNombre: 'Fiesta',
    backgroundImg: '/assets/esc-museosalsa.jpg',
    imagenPrompt: 'Museo de la Salsa en Santiago de Cali, ambiente cultural y festivo, fotografía profesional de alta calidad',
  },
  {
    id: 'plaza-varela',
    nombre: 'Plaza Varela',
    descripcion: 'La plaza histórica donde el latido de la salsa caleña se siente en cada paso, rodeada de vida y cultura.',
    gradiente: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 35%, #4c1d95 100%)',
    acento: '#a78bfa',
    icono: '💃',
    tags: ['Salsa', 'Cultura'],
    botellaImg: '/assets/botella-night.png',
    botellaNombre: 'Night',
    backgroundImg: '/assets/esc-plazavarela.jpg',
    imagenPrompt: 'Plaza Varela de Santiago de Cali al atardecer, fuente central, gente bailando salsa, fotografía de alta gama',
  },
  {
    id: 'cristo-rey',
    nombre: 'Cristo Rey',
    descripcion: 'La vista panorámica más imponente de la Capital Mundial de la Salsa, desde lo más alto de la ciudad.',
    gradiente: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 35%, #075985 100%)',
    acento: '#38bdf8',
    icono: '⛰️',
    tags: ['Panorámica', 'Ícono'],
    botellaImg: '/assets/botella-sin-azucar.png',
    botellaNombre: 'Sin Azúcar',
    backgroundImg: '/assets/esc-cristorey.jpg',
    imagenPrompt: 'Monumento del Cristo Rey de Santiago de Cali con vista panorámica de toda la ciudad, fotografía profesional 4k',
  },
]

export const ESCENARIO_MAP = ESCENARIOS.reduce((acc, e) => {
  acc[e.id] = e
  return acc
}, {})
