import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json'
  }
})

client.interceptors.response.use(
  response => response.data,
  error => {
    const errorMsg = error.response?.data?.detail || error.message || '网络请求异常'
    console.error('API Error:', errorMsg, error)
    return Promise.reject(new Error(errorMsg))
  }
)

export default client
