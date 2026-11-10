package com.example.pokemmobreederhelper.ui.main

import com.chaquo.python.PyObject
import com.chaquo.python.Python

/** UI planning tests use explicit listings, never the availability of a public server. */
internal class SyntheticMarket {
  private var original: PyObject? = null
  fun install() {
    val python = Python.getInstance()
    val builtins = python.getModule("builtins")
    val bridge = python.getModule("mobile_bridge")
    original = builtins.callAttr("getattr", bridge, "_purchase_market_snapshot")
    builtins.callAttr("exec", """
      def _instrumentation_market(current):
          from datetime import datetime, timezone, timedelta
          from market_data import parse_snapshot
          at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
          return parse_snapshot(dict(items=[], updatedAt=at, pokemonQueries=[
              dict(familyId=family, query=query, price=15000, quantity=100, listings=100, at=at)
              for family in (29, 32, 133)
              for query in ('male', 'female', 'alpha_male', 'alpha_female')
          ]))
      _purchase_market_snapshot = _instrumentation_market
    """.trimIndent(), builtins.callAttr("getattr", bridge, "__dict__"))
  }
  fun close() {
    original?.let { Python.getInstance().getModule("builtins")
      .callAttr("setattr", Python.getInstance().getModule("mobile_bridge"), "_purchase_market_snapshot", it) }
  }
}
