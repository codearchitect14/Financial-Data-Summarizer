import { Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'

interface Props {
  busy: boolean
  onSubmit: (ticker: string) => void
}

export function TickerSearch({ busy, onSubmit }: Props) {
  const [value, setValue] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const ticker = value.trim().toUpperCase()
    if (ticker && !busy) onSubmit(ticker)
  }

  return (
    <form onSubmit={handleSubmit} role="search" className="flex w-full max-w-md gap-2">
      <label htmlFor="ticker" className="sr-only">
        Stock ticker
      </label>
      <div className="relative flex-1">
        <Search aria-hidden className="absolute top-2.5 left-3 size-4 text-slate-400" />
        <input
          id="ticker"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Enter a ticker, such as AAPL"
          maxLength={12}
          autoComplete="off"
          spellCheck={false}
          className="h-9 w-full rounded-md border border-slate-300 bg-white pr-3 pl-9 text-sm uppercase placeholder:text-slate-400 placeholder:normal-case"
        />
      </div>
      <button
        type="submit"
        disabled={busy || !value.trim()}
        className="h-9 rounded-md bg-blue-700 px-4 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {busy ? 'Working…' : 'Get briefing'}
      </button>
    </form>
  )
}
