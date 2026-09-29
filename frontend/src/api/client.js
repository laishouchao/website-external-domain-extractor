import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request Interceptor: Attach JWT Bearer Token
client.interceptors.request.use(
  config => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// Response Interceptor: Unwrap data & Handle 401 Unauthorized
client.interceptors.response.use(
  response => response.data,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_info')
      if (window.location.pathname !== '/login') {
        const redirectUrl = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirectUrl}`
      }
    }

    const errorMsg = error.response?.data?.detail || error.message || '网络请求异常'
    console.error('API Error:', errorMsg, error)
    return Promise.reject(new Error(errorMsg))
  }
)

export default client
