// TED-ийн 3D толгой (three.js). Урсдаг кодын толгойн гэрэлтэлтийн зураглалыг (luminance map) гаргана.
// Загвар: Face Cap (bannaflak.com/face-cap) — three.js-ийн жишээ загвар, зөвхөн геометр + 11 морф үлдээв.
// Бүтээх: cd web/src && npm i three esbuild && npx esbuild head.js --bundle --minify --format=iife --global-name=TEDHead --outfile=../assets/ted-head.js
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export async function create(url) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(1);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 100);

  // Гэрэлтүүлэг: урд-зүүн гол гэрэл, баруун зөөлөн, ар талаас ирмэгийн (rim) гэрэл — нүүрний хэлбэр тод гарна
  scene.add(new THREE.AmbientLight(0xffffff, 0.03));
  const key = new THREE.DirectionalLight(0xffffff, 2.5); key.position.set(-0.95, 1.0, 2.3); scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.6); fill.position.set(1.4, -0.1, 1.5); scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffffff, 1.6); rim.position.set(0.4, 1.4, -2.5); scene.add(rim);
  const rim2 = new THREE.DirectionalLight(0xffffff, 1.0); rim2.position.set(-1.8, -0.2, -1.5); scene.add(rim2);

  const skin = new THREE.MeshStandardMaterial({ color: 0x3dff9a, roughness: 0.48, metalness: 0.05 });
  const eyeMat = new THREE.MeshStandardMaterial({ color: 0x0b3d24, roughness: 0.2, metalness: 0.0, emissive: 0x9dffd0, emissiveIntensity: 0 });
  const teethMat = new THREE.MeshStandardMaterial({ color: 0x1d7a4c, roughness: 0.6 });

  const gltf = await new GLTFLoader().loadAsync(url);
  const root = gltf.scene;
  let face = null;
  root.traverse(o => {
    if (!o.isMesh) return;
    const n = (o.name || '') + ' ' + (o.parent && o.parent.name || '');
    if (o.morphTargetDictionary && Object.keys(o.morphTargetDictionary).length) { face = o; o.material = skin; }
    else if (/eye/i.test(n)) o.material = eyeMat;
    else if (/teeth/i.test(n)) o.material = teethMat;
    else o.material = skin;
  });
  // Төвлөрүүлж, камерыг нүүрэнд тааруулна
  const box = new THREE.Box3().setFromObject(root), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const pivot = new THREE.Group(); scene.add(pivot);
  root.position.sub(c); pivot.add(root);
  const fitH = size.y * 0.74;
  camera.position.set(0, size.y * 0.04, fitH / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) + size.z * 0.5);
  camera.lookAt(0, size.y * 0.02, 0);

  const dict = face ? face.morphTargetDictionary : {};
  const infl = face ? face.morphTargetInfluences : [];
  const set = (k, v) => { const i = dict[k]; if (i !== undefined) infl[i] = v; };

  let rt = null, buf = null, rw = 0, rh = 0;
  return {
    canvas: renderer.domElement,
    resize(w, h) { renderer.setSize(Math.max(1, w | 0), Math.max(1, h | 0), false); camera.aspect = w / h; camera.updateProjectionMatrix(); },
    pose(p) {
      pivot.rotation.y = p.yaw || 0; pivot.rotation.x = p.pitch || 0; pivot.rotation.z = p.roll || 0;
      set('jawOpen', p.jaw || 0); set('mouthFunnel', p.funnel || 0); set('mouthClose', 0);
      set('eyeBlink_L', p.blink || 0); set('eyeBlink_R', p.blink || 0);
      set('mouthSmile_L', p.smile || 0); set('mouthSmile_R', p.smile || 0);
      set('browInnerUp', p.brow || 0); set('eyeWide_L', p.wide || 0); set('eyeWide_R', p.wide || 0);
      eyeMat.emissiveIntensity = p.eyeGlow || 0;
    },
    render() { renderer.setRenderTarget(null); renderer.render(scene, camera); },
    // Тор (cols×rows) бүрийн гэрэлтэлт 0..1 (ногоон сувгаас)
    sample(cols, rows) {
      if (!rt || rw !== cols || rh !== rows) {
        rt && rt.dispose(); rw = cols; rh = rows;
        rt = new THREE.WebGLRenderTarget(cols, rows, { samples: 4 }); buf = new Uint8Array(cols * rows * 4);
      }
      renderer.setRenderTarget(rt); renderer.clear(); renderer.render(scene, camera); renderer.setRenderTarget(null);
      renderer.readRenderTargetPixels(rt, 0, 0, cols, rows, buf);
      const out = new Float32Array(cols * rows);
      for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
        const k = ((rows - 1 - y) * cols + x) * 4;          // WebGL-ийн мөр доороос дээш
        out[y * cols + x] = buf[k + 1] / 255;
      }
      return out;
    },
  };
}
