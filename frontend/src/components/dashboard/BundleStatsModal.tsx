"use client";

import { FileMeta } from "@/lib/api";

interface BundleStatsModalProps {
  repoName: string;
  files: FileMeta[];
  onClose: () => void;
}

export function BundleStatsModal({ repoName, files, onClose }: BundleStatsModalProps) {
  // Compute type distribution
  const typeCounts: Record<string, number> = {};
  const tagCounts: Record<string, number> = {};

  files.forEach((f) => {
    const type = f.type || "module";
    typeCounts[type] = (typeCounts[type] || 0) + 1;

    if (f.tags) {
      f.tags.forEach((t) => {
        tagCounts[t] = (tagCounts[t] || 0) + 1;
      });
    }
  });

  const topTags = Object.entries(tagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);

  const totalFiles = files.length;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
      <div className="bg-brutal-white border-4 border-brutal-black shadow-brutal w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        
        {/* Header */}
        <div className="bg-brutal-green p-4 border-b-4 border-brutal-black flex justify-between items-center">
          <div>
            <h2 className="text-xl font-black uppercase tracking-tight">📊 BUNDLE ANALYTICS & INSIGHTS</h2>
            <p className="text-xs font-bold opacity-80">Repository: {repoName}</p>
          </div>
          <button
            onClick={onClose}
            className="bg-brutal-orange text-brutal-black font-black px-3 py-1 border-2 border-brutal-black hover:bg-brutal-white transition-colors"
          >
            CLOSE [X]
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto space-y-6">
          
          {/* Summary Stats Grid */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-yellow-100 p-4 border-3 border-brutal-black shadow-brutal text-center">
              <span className="text-3xl font-black block">{totalFiles}</span>
              <span className="text-[10px] font-bold uppercase text-gray-700">OKF Modules</span>
            </div>
            <div className="bg-purple-100 p-4 border-3 border-brutal-black shadow-brutal text-center">
              <span className="text-3xl font-black block">{Object.keys(typeCounts).length}</span>
              <span className="text-[10px] font-bold uppercase text-gray-700">Architecture Layers</span>
            </div>
            <div className="bg-green-100 p-4 border-3 border-brutal-black shadow-brutal text-center">
              <span className="text-3xl font-black block">{Object.keys(tagCounts).length}</span>
              <span className="text-[10px] font-bold uppercase text-gray-700">Concept Tags</span>
            </div>
          </div>

          {/* Module Types Breakdown */}
          <div className="border-3 border-brutal-black p-4 bg-white shadow-brutal">
            <h3 className="text-sm font-black uppercase mb-3 border-b-2 border-brutal-black pb-1">
              📂 Component Distribution
            </h3>
            <div className="space-y-2">
              {Object.entries(typeCounts).map(([type, count]) => {
                const pct = Math.round((count / totalFiles) * 100);
                return (
                  <div key={type} className="flex items-center text-xs">
                    <span className="w-24 font-bold uppercase truncate">{type}</span>
                    <div className="flex-1 h-3 border-2 border-brutal-black bg-gray-100 mx-2 overflow-hidden">
                      <div
                        className="h-full bg-brutal-orange border-r border-brutal-black"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-12 text-right font-black">{count} ({pct}%)</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Top Concept Tags (Architecture Hotspots) */}
          <div className="border-3 border-brutal-black p-4 bg-white shadow-brutal">
            <h3 className="text-sm font-black uppercase mb-3 border-b-2 border-brutal-black pb-1">
              🏷️ Architecture Hotspots (Top Tags)
            </h3>
            <div className="flex flex-wrap gap-2">
              {topTags.map(([tag, count]) => (
                <span
                  key={tag}
                  className="bg-brutal-gray border-2 border-brutal-black px-2 py-1 text-xs font-bold flex items-center gap-1 shadow-brutal-sm"
                >
                  <span>#{tag}</span>
                  <span className="bg-brutal-black text-white text-[9px] px-1 font-black">{count}</span>
                </span>
              ))}
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="p-3 bg-brutal-gray border-t-3 border-brutal-black text-center text-xs font-bold">
          CodeMind OKF Knowledge Graph Stats • Deterministic AST Parsing
        </div>
      </div>
    </div>
  );
}
