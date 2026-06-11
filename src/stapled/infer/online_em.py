"""Online EM for streaming Dawid-Skene (Cappé-Moulines)."""

import sqlite3
import numpy as np
import json
from datetime import datetime
from typing import Dict, List


class OnlineEM:
    """Online EM with Robbins-Monro step size."""

    def __init__(
        self,
        outlet_ids: List[int],
        tolerance: float = 1e-5,
        conn: sqlite3.Connection = None,
        dedup_voting: bool = True,
    ):
        """
        Initialize online EM state. Load prior from em_state table if available.

        Args:
            outlet_ids: List of outlet IDs
            tolerance: Convergence tolerance
            conn: Database connection (optional, set via connect())
            dedup_voting: If True, count near-duplicate clusters as one fractional vote
        """
        self.outlet_ids = outlet_ids
        self.tolerance = tolerance
        self.conn: sqlite3.Connection = conn
        self.dedup_voting = dedup_voting

        # Initialize parameters: uninformative 0.7 if no prior
        self.sens = {o: 0.7 for o in outlet_ids}
        self.spec = {o: 0.7 for o in outlet_ids}
        self.exp_tp = {o: 0.0 for o in outlet_ids}
        self.exp_fp = {o: 0.0 for o in outlet_ids}
        self.exp_tn = {o: 0.0 for o in outlet_ids}
        self.exp_fn = {o: 0.0 for o in outlet_ids}
        self.n_obs = {o: 0 for o in outlet_ids}
        self.pi = 0.5
        self.ll_trace = []

        # Load from em_state if available; create if missing
        if conn:
            self._ensure_em_state(conn)
            self._load_state(conn)

    def _ensure_em_state(self, conn: sqlite3.Connection) -> None:
        """Ensure em_state row with id=1 exists, create if missing."""
        try:
            cursor = conn.execute("SELECT 1 FROM em_state WHERE id = 1")
            if not cursor.fetchone():
                conn.execute(
                    """INSERT INTO em_state
                       (id, prior_pi, batches_seen, ll_trace_json, updated_at)
                       VALUES (1, 0.5, 0, '[]', ?)""",
                    (datetime.utcnow().isoformat(),)
                )
                conn.commit()
        except Exception:
            pass

    def _load_state(self, conn: sqlite3.Connection) -> None:
        """Load em_state and suffstats from database."""
        try:
            cursor = conn.execute("SELECT prior_pi, ll_trace_json FROM em_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self.pi = row[0] if row[0] is not None else 0.5
                if row[1]:
                    self.ll_trace = json.loads(row[1])
        except Exception:
            pass

        # Load suffstats
        try:
            cursor = conn.execute(
                "SELECT outlet_id, exp_tp, exp_fp, exp_tn, exp_fn, n_obs FROM em_suffstats"
            )
            for outlet_id, exp_tp, exp_fp, exp_tn, exp_fn, n_obs in cursor.fetchall():
                if outlet_id in self.outlet_ids:
                    self.exp_tp[outlet_id] = exp_tp if exp_tp else 0.0
                    self.exp_fp[outlet_id] = exp_fp if exp_fp else 0.0
                    self.exp_tn[outlet_id] = exp_tn if exp_tn else 0.0
                    self.exp_fn[outlet_id] = exp_fn if exp_fn else 0.0
                    self.n_obs[outlet_id] = n_obs if n_obs else 0

                    # Derive sens/spec
                    tp = self.exp_tp[outlet_id]
                    fp = self.exp_fp[outlet_id]
                    tn = self.exp_tn[outlet_id]
                    fn = self.exp_fn[outlet_id]

                    self.sens[outlet_id] = tp / (tp + fn) if (tp + fn) > 0 else 0.7
                    self.spec[outlet_id] = tn / (tn + fp) if (tn + fp) > 0 else 0.7
        except Exception:
            pass

    def connect(self, conn: sqlite3.Connection) -> None:
        """Bind database connection."""
        self.conn = conn

    def ensure_outlets(self, outlet_ids: List[int]) -> None:
        """Register outlets discovered after init (streaming creates outlets lazily)."""
        for o in outlet_ids:
            if o not in self.sens:
                self.outlet_ids.append(o)
                self.sens[o] = 0.7
                self.spec[o] = 0.7
                self.exp_tp[o] = 0.0
                self.exp_fp[o] = 0.0
                self.exp_tn[o] = 0.0
                self.exp_fn[o] = 0.0
                self.n_obs[o] = 0
                if hasattr(self, "_prev_sens"):
                    self._prev_sens[o] = 0.7

    def e_step_batch(self, events):
        """
        E-step on batch of events.

        Args:
            events: Either:
              - List[Dict] of {event_id, claims: [{outlet_id, observation, certainty}]}
              - List[int] of event IDs (loads from DB)

        Returns:
            For dict input: {event_id → [P(s=0), P(s=1)]}
            For ID input: Dict with keys: "posteriors", "batch_stats", "batch_ll"
        """
        # Detect format
        if events and isinstance(events[0], dict) and "event_id" in events[0]:
            return self._e_step_from_dicts(events)
        elif events and isinstance(events[0], int):
            return self._e_step_from_ids(events)
        else:
            raise ValueError("Invalid event input format")

    def _e_step_from_dicts(self, events: List[Dict]) -> Dict[int, np.ndarray]:
        """E-step from event dicts."""
        posteriors = {}

        for event in events:
            event_id = event["event_id"]
            claims = event["claims"]
            self.ensure_outlets([c["outlet_id"] for c in claims])

            # Check for anchor
            anchor_true_state = self._get_anchor(event_id) if self.conn else None

            # Compute likelihood per state
            ll_s0 = (1.0 - self.pi)
            ll_s1 = self.pi

            for claim in claims:
                outlet_id = claim["outlet_id"]
                obs = claim["observation"]
                cert = claim.get("certainty", 0.5)
                w = claim.get("weight", 1.0)

                sens = self.sens[outlet_id]
                spec = self.spec[outlet_id]

                # P(obs | state, sens, spec, cert)
                for true_state in [0, 1]:
                    if true_state == 1:
                        p_correct = sens
                    else:
                        p_correct = spec

                    # Certainty as temperature
                    p_correct = p_correct * cert + (1 - cert) * 0.5
                    p_correct = np.clip(p_correct, 1e-9, 1 - 1e-9)

                    p_obs_given_state = p_correct if obs == true_state else 1 - p_correct

                    # Apply fractional weight via exponentiation
                    p_obs_given_state = p_obs_given_state ** w

                    if true_state == 0:
                        ll_s0 *= p_obs_given_state
                    else:
                        ll_s1 *= p_obs_given_state

            # Normalize
            total = ll_s0 + ll_s1
            if total > 0:
                p_s0 = ll_s0 / total
                p_s1 = ll_s1 / total
            else:
                p_s0 = p_s1 = 0.5

            # Clamp to anchor if exists
            if anchor_true_state is not None:
                if anchor_true_state == 0:
                    p_s0, p_s1 = 0.99, 0.01
                else:
                    p_s0, p_s1 = 0.01, 0.99

            # Clip to avoid extremes
            p_s0 = np.clip(p_s0, 1e-9, 1 - 1e-9)
            p_s1 = np.clip(p_s1, 1e-9, 1 - 1e-9)

            # Renormalize
            total = p_s0 + p_s1
            p_s0 /= total
            p_s1 /= total

            posteriors[event_id] = np.array([p_s0, p_s1])

        return posteriors

    def _e_step_from_ids(self, event_ids: List[int], outlet_params: Dict = None) -> Dict[str, any]:
        """
        E-step on batch of events, loading from database.

        Args:
            event_ids: List of event IDs to process
            outlet_params: Optional outlet parameters

        Returns:
            Dict with keys: "posteriors", "batch_stats", "batch_ll"
        """
        if not self.conn:
            raise ValueError("No database connection set")

        posteriors = {}
        batch_stats = {o: {
            "sens": self.sens[o],
            "spec": self.spec[o],
            "exp_tp": 0.0,
            "exp_fp": 0.0,
            "exp_tn": 0.0,
            "exp_fn": 0.0,
            "n_obs": 0.0,
        } for o in self.outlet_ids}
        batch_ll = 0.0

        # Load events and claims from DB
        placeholders = ",".join("?" * len(event_ids))
        cursor = self.conn.execute(
            f"""
            SELECT e.id, json_group_array(json_object(
                'outlet_id', a.outlet_id,
                'observation', CASE WHEN c.action LIKE 'not-%' OR c.action IN ('did-not-occur', 'did not occur') THEN 0 ELSE 1 END,
                'certainty', COALESCE(c.certainty, 0.5),
                'vote_key', CASE WHEN a.dedup_cluster_id IS NOT NULL THEN 'c' || a.dedup_cluster_id ELSE 'a' || a.id END
            )) as claims_json
            FROM event e
            JOIN claim c ON e.id = c.event_id
            JOIN article a ON c.article_id = a.id
            WHERE e.id IN ({placeholders})
            GROUP BY e.id
            """,
            event_ids,
        )
        event_rows = cursor.fetchall()

        for event_id, claims_json in event_rows:
            claims = json.loads(claims_json)

            # Register outlets created after EM init (streaming adds outlets lazily)
            claim_outlets = {c["outlet_id"] for c in claims}
            self.ensure_outlets(list(claim_outlets))
            for o in claim_outlets:
                if o not in batch_stats:
                    batch_stats[o] = {
                        "sens": self.sens[o],
                        "spec": self.spec[o],
                        "exp_tp": 0.0,
                        "exp_fp": 0.0,
                        "exp_tn": 0.0,
                        "exp_fn": 0.0,
                        "n_obs": 0.0,
                    }

            # Compute per-claim weight based on dedup clustering
            if self.dedup_voting:
                vote_key_counts = {}
                for claim in claims:
                    vk = claim.get("vote_key", f"a{id(claim)}")
                    vote_key_counts[vk] = vote_key_counts.get(vk, 0) + 1

                for claim in claims:
                    vk = claim.get("vote_key", f"a{id(claim)}")
                    claim["weight"] = 1.0 / vote_key_counts[vk]
            else:
                for claim in claims:
                    claim["weight"] = 1.0

            # Check for anchor
            anchor_true_state = self._get_anchor(event_id)

            # Compute likelihood per state
            ll_s0 = (1.0 - self.pi)
            ll_s1 = self.pi

            for claim in claims:
                outlet_id = claim["outlet_id"]
                obs = claim["observation"]
                cert = claim.get("certainty", 0.5)
                w = claim.get("weight", 1.0)

                sens = self.sens[outlet_id]
                spec = self.spec[outlet_id]

                # P(obs | state, sens, spec, cert)
                for true_state in [0, 1]:
                    if true_state == 1:
                        p_correct = sens
                    else:
                        p_correct = spec

                    # Certainty as temperature
                    p_correct = p_correct * cert + (1 - cert) * 0.5
                    p_correct = np.clip(p_correct, 1e-9, 1 - 1e-9)

                    p_obs_given_state = p_correct if obs == true_state else 1 - p_correct

                    # Apply fractional weight via exponentiation
                    p_obs_given_state = p_obs_given_state ** w

                    if true_state == 0:
                        ll_s0 *= p_obs_given_state
                    else:
                        ll_s1 *= p_obs_given_state

            # Normalize
            total = ll_s0 + ll_s1
            if total > 0:
                p_s0 = ll_s0 / total
                p_s1 = ll_s1 / total
            else:
                p_s0 = p_s1 = 0.5

            # Clamp to anchor if exists
            if anchor_true_state is not None:
                if anchor_true_state == 0:
                    p_s0, p_s1 = 0.99, 0.01
                else:
                    p_s0, p_s1 = 0.01, 0.99

            # Clip to avoid extremes
            p_s0 = np.clip(p_s0, 1e-9, 1 - 1e-9)
            p_s1 = np.clip(p_s1, 1e-9, 1 - 1e-9)

            # Renormalize
            total = p_s0 + p_s1
            p_s0 /= total
            p_s1 /= total

            posteriors[event_id] = np.array([p_s0, p_s1])

            # Accumulate batch statistics
            for claim in claims:
                outlet_id = claim["outlet_id"]
                obs = claim["observation"]
                cert = claim.get("certainty", 0.5)
                w = claim.get("weight", 1.0)

                if obs == 1:
                    batch_stats[outlet_id]["exp_tp"] += p_s1 * cert * w
                    batch_stats[outlet_id]["n_obs"] += p_s1 * cert * w
                else:
                    batch_stats[outlet_id]["exp_fn"] += p_s1 * cert * w
                    batch_stats[outlet_id]["n_obs"] += p_s1 * cert * w

                if obs == 0:
                    batch_stats[outlet_id]["exp_tn"] += p_s0 * cert * w
                else:
                    batch_stats[outlet_id]["exp_fp"] += p_s0 * cert * w

            # Compute log-likelihood
            for claim in claims:
                outlet_id = claim["outlet_id"]
                obs = claim["observation"]
                cert = claim.get("certainty", 0.5)
                w = claim.get("weight", 1.0)

                sens = self.sens[outlet_id]
                spec = self.spec[outlet_id]

                p_correct_s1 = sens * cert + (1 - cert) * 0.5
                p_correct_s0 = spec * cert + (1 - cert) * 0.5
                p_correct_s1 = np.clip(p_correct_s1, 1e-9, 1 - 1e-9)
                p_correct_s0 = np.clip(p_correct_s0, 1e-9, 1 - 1e-9)

                p_obs_s1 = p_correct_s1 if obs == 1 else 1 - p_correct_s1
                p_obs_s0 = p_correct_s0 if obs == 0 else 1 - p_correct_s0

                p_s0 = posteriors[event_id][0]
                p_s1 = posteriors[event_id][1]
                batch_ll += w * np.log(p_s0 * p_obs_s0 + p_s1 * p_obs_s1 + 1e-10)

        return {
            "posteriors": posteriors,
            "batch_stats": batch_stats,
            "batch_ll": float(batch_ll),
        }

    def accumulate(self, batch_stats: Dict, t: int) -> None:
        """
        Accumulate batch statistics with Robbins-Monro step size.

        Args:
            batch_stats: {outlet_id → {sens, spec, exp_tp, exp_fp, exp_tn, exp_fn, n_obs}}
            t: Batch index (0-indexed)
        """
        # Robbins-Monro: γ_t = (t+2)**-0.6
        gamma = (t + 2.0) ** (-0.6)

        for outlet_id in self.outlet_ids:
            if outlet_id not in batch_stats:
                continue

            stats = batch_stats[outlet_id]

            # Update sens/spec
            self.sens[outlet_id] = (1 - gamma) * self.sens[outlet_id] + gamma * stats["sens"]
            self.spec[outlet_id] = (1 - gamma) * self.spec[outlet_id] + gamma * stats["spec"]

            # Update expected confusion matrix counts
            self.exp_tp[outlet_id] = (1 - gamma) * self.exp_tp[outlet_id] + gamma * stats["exp_tp"]
            self.exp_fp[outlet_id] = (1 - gamma) * self.exp_fp[outlet_id] + gamma * stats["exp_fp"]
            self.exp_tn[outlet_id] = (1 - gamma) * self.exp_tn[outlet_id] + gamma * stats["exp_tn"]
            self.exp_fn[outlet_id] = (1 - gamma) * self.exp_fn[outlet_id] + gamma * stats["exp_fn"]

            self.n_obs[outlet_id] = (1 - gamma) * self.n_obs[outlet_id] + gamma * stats["n_obs"]

            # Persist to DB
            self.conn.execute(
                """INSERT INTO em_suffstats (outlet_id, exp_tp, exp_fp, exp_tn, exp_fn, n_obs)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(outlet_id) DO UPDATE SET
                   exp_tp=excluded.exp_tp, exp_fp=excluded.exp_fp,
                   exp_tn=excluded.exp_tn, exp_fn=excluded.exp_fn, n_obs=excluded.n_obs""",
                (
                    outlet_id,
                    self.exp_tp[outlet_id],
                    self.exp_fp[outlet_id],
                    self.exp_tn[outlet_id],
                    self.exp_fn[outlet_id],
                    self.n_obs[outlet_id],
                ),
            )

            # Compute and store reliability snapshot
            tp = self.exp_tp[outlet_id]
            fp = self.exp_fp[outlet_id]
            tn = self.exp_tn[outlet_id]
            fn = self.exp_fn[outlet_id]

            sens = tp / (tp + fn) if (tp + fn) > 0 else 0.5
            spec = tn / (tn + fp) if (tn + fp) > 0 else 0.5
            reliability = (sens + spec) / 2.0

            self.conn.execute(
                """INSERT INTO reliability_snapshot (batch, outlet_id, reliability)
                   VALUES (?, ?, ?)
                   ON CONFLICT(batch, outlet_id) DO UPDATE SET reliability=excluded.reliability""",
                (t, outlet_id, reliability),
            )

        # Update prior
        self.pi = np.clip(self.pi, 0.01, 0.99)

        # Persist state
        self.ll_trace.append(batch_stats.get("ll", 0.0))
        self.conn.execute(
            """INSERT INTO em_state (id, prior_pi, batches_seen, ll_trace_json, updated_at)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               prior_pi=excluded.prior_pi, batches_seen=excluded.batches_seen,
               ll_trace_json=excluded.ll_trace_json, updated_at=excluded.updated_at""",
            (
                self.pi,
                len(self.ll_trace),
                json.dumps(self.ll_trace),
                datetime.utcnow().isoformat(),
            ),
        )

        self.conn.commit()

    def params(self) -> Dict[int, Dict[str, float]]:
        """
        Get current parameters.

        Returns:
            {outlet_id → {sens, spec, reliability, bias}}
        """
        result = {}
        for outlet_id in self.outlet_ids:
            tp = self.exp_tp[outlet_id]
            fp = self.exp_fp[outlet_id]
            tn = self.exp_tn[outlet_id]
            fn = self.exp_fn[outlet_id]

            sens = tp / (tp + fn) if (tp + fn) > 0 else 0.5
            spec = tn / (tn + fp) if (tn + fp) > 0 else 0.5

            sens = np.clip(sens, 0.01, 0.99)
            spec = np.clip(spec, 0.01, 0.99)

            result[outlet_id] = {
                "sens": float(sens),
                "spec": float(spec),
                "reliability": float((sens + spec) / 2.0),
                "bias": float(sens - spec),
            }

        return result

    def m_params(self) -> tuple:
        """
        Compute M-step parameters from sufficient statistics.

        Returns:
            (sens_dict, spec_dict, reliability_dict, bias_dict)
        """
        params = self.params()
        sens_dict = {o: p["sens"] for o, p in params.items()}
        spec_dict = {o: p["spec"] for o, p in params.items()}
        reliability_dict = {o: p["reliability"] for o, p in params.items()}
        bias_dict = {o: p["bias"] for o, p in params.items()}

        return sens_dict, spec_dict, reliability_dict, bias_dict

    def converged(self, l2_tol: float = 1e-5) -> bool:
        """
        Check convergence: L2 norm of (sens_prev - sens_curr) < l2_tol.

        Args:
            l2_tol: Tolerance threshold

        Returns:
            True if converged, False otherwise
        """
        if not hasattr(self, '_prev_sens'):
            self._prev_sens = {o: self.sens[o] for o in self.outlet_ids}
            return False

        # L2 distance of sens parameters
        delta_sq = sum((self.sens[o] - self._prev_sens[o]) ** 2 for o in self.outlet_ids)
        l2_delta = np.sqrt(delta_sq)

        # Update prev
        self._prev_sens = {o: self.sens[o] for o in self.outlet_ids}

        return l2_delta < l2_tol

    def _get_anchor(self, event_id: int) -> int:
        """Fetch anchor true_state for event, or None."""
        if not self.conn:
            return None

        cursor = self.conn.execute(
            "SELECT true_state FROM anchor WHERE event_id = ?",
            (event_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def _regression_test_vs_em(self, baseline_em: dict) -> bool:
        """
        Regression test: online EM sens/spec within delta<0.05 vs baseline EM.
        Internal test for validation.

        Args:
            baseline_em: {outlet_id → {sens, spec}}

        Returns:
            True if all deltas < 0.05, False otherwise
        """
        for outlet_id in self.outlet_ids:
            if outlet_id not in baseline_em:
                continue
            baseline = baseline_em[outlet_id]
            delta_sens = abs(self.sens[outlet_id] - baseline['sens'])
            delta_spec = abs(self.spec[outlet_id] - baseline['spec'])
            if delta_sens >= 0.05 or delta_spec >= 0.05:
                return False
        return True
