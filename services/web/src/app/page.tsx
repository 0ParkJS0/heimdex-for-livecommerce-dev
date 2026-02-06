"use client";

import { useState, useCallback } from "react";
import { SearchBar } from "@/components/SearchBar";
import { AlphaSlider } from "@/components/AlphaSlider";
import { FilterPanel } from "@/components/FilterPanel";
import { SearchResults } from "@/components/SearchResults";
import {
  search,
  SearchFilters,
  SearchResponse,
} from "@/lib/api";

export default function Home() {
  const [alpha, setAlpha] = useState(0.5);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDebug, setShowDebug] = useState(false);
  const [lastQuery, setLastQuery] = useState("");

  const handleSearch = useCallback(
    async (query: string) => {
      setIsLoading(true);
      setError(null);
      setLastQuery(query);

      try {
        const result = await search({
          q: query,
          alpha,
          filters,
        });
        setResponse(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
        setResponse(null);
      } finally {
        setIsLoading(false);
      }
    },
    [alpha, filters]
  );

  const handleFiltersChange = (newFilters: SearchFilters) => {
    setFilters(newFilters);
    if (lastQuery) {
      handleSearch(lastQuery);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Heimdex</h1>
                <p className="text-xs text-gray-500">Video Search Platform</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">
                Org: <span className="font-medium text-gray-700">devorg</span>
              </span>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showDebug}
                  onChange={(e) => setShowDebug(e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                Debug Mode
              </label>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="mb-6 space-y-4">
          <SearchBar onSearch={handleSearch} isLoading={isLoading} />
          
          <div className="card p-4">
            <AlphaSlider value={alpha} onChange={setAlpha} />
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            <p className="font-medium">Search Error</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        <div className="flex gap-6">
          <aside className="w-64 flex-shrink-0">
            <div className="card p-4 sticky top-4">
              <FilterPanel
                facets={response?.facets ?? null}
                filters={filters}
                onFiltersChange={handleFiltersChange}
              />
            </div>
          </aside>

          <div className="flex-1 min-w-0">
            {response ? (
              <SearchResults
                results={response.results}
                totalCandidates={response.total_candidates}
                showDebug={showDebug}
              />
            ) : (
              <div className="text-center py-16 text-gray-500">
                <svg
                  className="w-16 h-16 mx-auto mb-4 text-gray-300"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
                <p className="text-lg font-medium">Search your video library</p>
                <p className="text-sm mt-1">
                  Enter a search query above to find scenes in your videos.
                  <br />
                  Supports both English and Korean.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-gray-200 mt-12 py-6">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-gray-500">
          <p>Heimdex v0.1.0 - Development Build</p>
          <p className="mt-1">
            Video playback requires the Heimdex agent running on your machine.
          </p>
        </div>
      </footer>
    </div>
  );
}
