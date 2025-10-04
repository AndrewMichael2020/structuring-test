import SiteLayout from '../layouts/SiteLayout.jsx';
import Container from '../components/Container.jsx';
import { Link } from 'react-router-dom';

export default function AboutPage() {
  return (
    <SiteLayout>
      <Container>
        <div className="max-w-3xl mx-auto prose prose-slate">
          <h1>About This Project</h1>
          <p>
            Mountain travel invites a rare mix of freedom, responsibility, and humility. Each incident on rock, ice, snow, and alpine ground contains a thread of insight—small decisions, environmental shifts, gear choices, human factors—that can help the next party return safe. Too many of those stories fragment across fleeting news blurbs, social posts, or terse rescue summaries and then fade. This project gathers them while they are still fresh and holds them in one living, open ledger so lessons stay accessible to climbers, skiers, scramblers, rescuers, and families seeking clarity.
          </p>
          <p>
            The aim is simple: turn scattered public reporting into durable knowledge. A structured record for each event keeps essential facts visible—what happened, where, conditions described, response actions, and uncertainties—so patterns emerge across terrain, season, style, and outcome. When pattern awareness rises, judgment sharpens. Judgment sharpens and margins widen. Margins widen and more people get home. That quiet chain of improvement is the real measure of value here.
          </p>
          <p>
            Every report you read in this interface is traceable back to its openly cited sources. Nothing is hidden behind proprietary analysis. Each narrative is generated with a restrained, factual tone and highlights what remains unknown—a prompt to remain curious, not complacent. The goal is not spectacle; it is clarity, respect, and continuity. Where possible, the voice favors measured description over drama, acknowledging that these incidents sit within real communities of partners, rescuers, and loved ones.
          </p>
          <p>
            The collection evolves as public information appears. Sources are preserved verbatim so you can review original context. Agency mentions, location descriptors, and environmental cues are kept intact to allow future comparison and deeper study. The structure lets practitioners track recurring themes: transitional terrain slips, late descent timing, anchor redundancy gaps, weather exposure, navigational drift, communication gaps, avalanche conditions, crevasse fall contexts, evolving mixed conditions—signals that help refine preparation and on-route choices.
          </p>
          <p>
            This is also an act of preservation. Headlines rotate. Links break. Hosting platforms redesign. A neutral ledger sustains continuity so a lesson from a shoulder season ridge fall or a mid-winter gully avalanche still informs a decision months or years later. Accessible knowledge lowers the barrier to reflective practice. Reflective practice raises collective baseline judgment. Elevating baseline judgment advances safety culture one small, steady step at a time.
          </p>
          <p>
            If you find value here, share a report with a partner, a new leader, a course student, or someone planning their first longer alpine route. Use it to spark specific what-if conversations. What if descent timing changed? What if a backup was added? What if a satellite communicator was active sooner? Incremental questioning compounds into experience.
          </p>
          <p>
            You are welcome to explore, reference, and build upon the material. The intent is open stewardship—maintaining a clear, respectful record that supports learning without assigning blame. Every safe return seeded by a prior lesson honors those involved in earlier events.
          </p>
          <p>
            Thank you for reading with care. Continue refining systems. Continue mentoring. Continue sharing specifics, not just outcomes. The mountains remain the same; how we prepare and adapt can change.
          </p>
          <p>
            Sincerely,
            <br />
            <br />
            <strong>Andrew M. Ihnativ</strong>
          </p>
          <p className="text-sm text-gray-500">Return to the <Link to="/" className="underline">home page</Link>.</p>
        </div>
      </Container>
    </SiteLayout>
  );
}
