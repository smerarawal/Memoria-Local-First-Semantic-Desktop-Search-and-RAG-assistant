// Tiny pixel-icon renderer: original 1-bit-style icons drawn from text bitmaps (no external assets).
const P = { k: '#000', w: '#fff', y: '#f2d45c', b: '#000080', c: '#7fd4ff', g: '#808080' }
const I = {
  folder: ['..kkk.....', '.kyyyk....', 'kkkkkkkkk.', 'kyyyyyyyyk', 'kyyyyyyyyk', 'kyyyyyyyyk', 'kyyyyyyyyk', 'kkkkkkkkkk'],
  doc: ['kkkkkk..', 'kwwwwkk.', 'kwwwwkwk', 'kwbbwkkk', 'kwwwwwwk', 'kwbbbbwk', 'kwwwwwwk', 'kwbbbbwk', 'kwwwwwwk', 'kkkkkkkk'],
  find: ['..kkkk....', '.kccccck..', 'kccwcccck.', 'kcccccck..', 'kcccccck..', '.kcccck...', '..kkkkk...', '.....kbk..', '......kbk.', '.......kk.'],
  pc: ['kkkkkkkkkk', 'kbbbbbbbbk', 'kbccccccbk', 'kbccccccbk', 'kbbbbbbbbk', 'kkkkkkkkkk', '.kgggggggk', '.kkkkkkkkk'],
}
export default function Px({ n, s = 2 }) {
  const r = I[n]
  return (
    <svg width={r[0].length * s} height={r.length * s} shapeRendering="crispEdges" style={{ flex: 'none' }}>
      {r.flatMap((row, y) => [...row].map((c, x) => P[c] && <rect key={x + ',' + y} x={x * s} y={y * s} width={s} height={s} fill={P[c]} />))}
    </svg>
  )
}
