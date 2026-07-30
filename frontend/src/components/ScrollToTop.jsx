import { useEffect } from 'react'

export default function ScrollToTop({ pathname, section }) {
  useEffect(() => {
    window.scrollTo({
      top: 0,
      left: 0,
      behavior: 'auto',
    })
  }, [pathname, section])

  return null
}
