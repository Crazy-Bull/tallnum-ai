// Windows sandbox can deny the native realpath syscall for ordinary files.
// Vite only needs the resolved path; Node's non-native variant works there.
const fs = require('node:fs')
const native = fs.realpathSync.native
fs.realpathSync.native = (path, options) => {
  try { return native(path, options) }
  catch (error) {
    if (error.code !== 'EPERM') throw error
    return fs.realpathSync(path, options)
  }
}
