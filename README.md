# Audio Monitor — Rode NT USB+

Monitorea el audio del micrófono en tiempo real mientras grabas en OBS. Si el audio se corrompe, se desconecta el cable USB, o hay un problema — aparece una alerta en tu pantalla inmediatamente.

---

## Qué detecta

| Problema | Tiempo de detección | Qué pasa |
|---|---|---|
| **Audio corrupto** (robótico/estático) | ~5 segundos | Overlay rojo + sonido de alerta |
| **Cable USB desconectado** | 2 segundos | Overlay rojo + sonido de alerta |
| **Silencio prolongado** (3+ min) | 3 minutos | Overlay naranja (red de seguridad) |

---

## Instalación (una sola vez)

### Mac

1. Abre **Terminal** (búscalo en Spotlight con `Cmd + Espacio`, escribe "Terminal")

2. Copia y pega este comando:
```bash
cd ~/Desktop && git clone https://github.com/todoloanterior/audio-monitor.git && cd audio-monitor && bash setup.sh
```

3. Espera a que termine. Verás un overlay verde que dice **"Setup Complete!"**

4. Listo. La carpeta `audio-monitor` queda en tu Escritorio.

### Windows

1. Descarga el proyecto desde GitHub (botón verde "Code" → "Download ZIP")
2. Extrae la carpeta en donde quieras
3. Doble clic en `start-monitor.bat`

---

## Cómo usar (cada vez que grabes)

### Paso 1: Abre Rode Connect
Abre la app de Rode Connect como siempre. El micrófono debe estar conectado.

### Paso 2: Inicia el monitor
- **Mac:** Doble clic en `start-monitor.command`
- **Windows:** Doble clic en `start-monitor.bat`

Se abre una ventana negra con un medidor de audio. Déjala abierta.

### Paso 3: Graba en OBS
Graba como siempre. El monitor corre en el fondo.

### Paso 4: Si hay un problema
- Aparece un **cuadro rojo** en la esquina superior derecha de tu pantalla
- Suena un **beep de alerta**
- El mensaje te dice qué pasó (cable desconectado, audio corrupto, etc.)

### Paso 5: Cuando termines
Cierra la ventana negra del monitor (clic en la X o `Ctrl+C`).

---

## Verificar que funciona (test con archivo incluido)

El repo incluye `test-sample.mp4` — un archivo de 60 segundos con audio corrupto a partir del segundo 25. Úsalo para verificar que todo funciona correctamente.

### Test rápido (analiza el archivo sin overlays)

```bash
python3 test_file.py test-sample.mp4
```

**Resultado esperado:**
- Baseline kurtosis: ~16
- Primera alerta de CORRUPTION alrededor del segundo 27-28
- 0 alertas antes del segundo 25 (cero falsos positivos)
- ~20+ alertas de CORRUPTION después del segundo 25

Si ves esto, el detector funciona correctamente.

### Test con overlays en tiempo real (demo visual)

```bash
python3 demo_file.py test-sample.mp4
```

**Qué vas a ver:**
- Un medidor de audio con timestamp avanzando en tiempo real
- A los ~27 segundos: overlay rojo **"Audio Corrupted!"** + beeps de alerta
- Las alertas siguen apareciendo cada ~15 segundos mientras el audio esté corrupto

Este es el mejor test para mostrarle a alguien cómo funciona la herramienta.

### Test en vivo con el micrófono

1. Abre Rode Connect
2. Ejecuta `python3 monitor.py`
3. Habla normalmente durante 15 segundos → no debe haber alertas
4. Desconecta el cable USB → alerta **"Signal Lost!"** en 2 segundos
5. Reconecta el cable → el monitor sigue funcionando

---

## Solución de problemas

### "No se encontró el micrófono"
- Asegúrate de que **Rode Connect esté abierto** antes de iniciar el monitor
- Verifica que el cable USB esté bien conectado

### "Python no está instalado"
- Ejecuta `bash setup.sh` de nuevo en Terminal

### El monitor no detecta mi micrófono
- Cuando aparezca la lista de dispositivos, escribe el **número** del dispositivo correcto y presiona Enter
- Busca uno que diga "RODE", "Virtual Input", o similar

### Quiero probar que funciona
- Habla normalmente → el medidor sube y baja (esto es normal)
- Desconecta el cable USB → debe aparecer alerta "Signal Lost!" en 2 segundos
- Reconecta y sigue

---

## Archivos incluidos

| Archivo | Para qué sirve |
|---|---|
| `start-monitor.command` | Doble clic para iniciar (Mac) |
| `start-monitor.bat` | Doble clic para iniciar (Windows) |
| `monitor.py` | El programa principal |
| `config.py` | Configuración (no tocar) |
| `test_file.py` | Analizar un archivo de audio/video |
| `demo_file.py` | Demo en tiempo real con un archivo |
| `setup.sh` | Instalador para Mac (solo la primera vez) |
| `test-sample.mp4` | Archivo de prueba (audio corrupto a partir de 25s) |
