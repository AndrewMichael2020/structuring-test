import SiteLayout from '../layouts/SiteLayout.jsx';
import Container from '../components/Container.jsx';
import { Link } from 'react-router-dom';

export default function AboutPage() {
  return (
    <SiteLayout>
      <Container>
        <div className="max-w-3xl mx-auto prose prose-slate">
          <h1>About This Project</h1>

          <h2>Why this app?</h2>
          <p>
            Accident details appear briefly in news posts or short summaries, then scatter. Before long, memory fades. This project aggregates information across public sources, enriches facts into a consistent structure, and keeps traceability so anyone can check the originals. Goal: raise baseline judgment and widen margins so more people get home.
          </p>

          <h2>Who it’s for?</h2>
          <ul>
            <li>Mountaineers, climbers, scramblers, hikers</li>
            <li>Hiking and climbing partners</li>
            <li>Outdoor clubs and community groups</li>
            <li>Trip organizers in volunteer settings</li>
            <li>Course participants and peer-led training groups</li>
          </ul>

          <h2>What each report contains?</h2>
          <ul>
            <li>Essential facts: what happened, where, when, terrain, conditions, outcome</li>
            <li>Response context: who assisted, actions taken, logistics that affected timing</li>
            <li>Causal signals: environmental, equipment, and human factors</li>
            <li>Uncertainties: what remains unclear</li>
            <li>Source links: every fact points to a cited source for verification</li>
          </ul>

          <h2>Aggregatable and mappable metrics</h2>
          <p>Each report standardizes fields so you can analyze and map patterns:</p>
          <ul>
            <li>Counts: people involved, injured, rescued, fatalities</li>
            <li>Distances and scale: estimated fall or slide distance, approach length</li>
            <li>Time: date, season, time-of-day buckets, daylight vs headlamp</li>
            <li>Terrain and style: rock, snow, ice, mixed; roped, unroped, rappel, downclimb</li>
            <li>Location: region, area, route name when public; latitude/longitude when available</li>
            <li>Conditions: weather notes, surface state, avalanche context</li>
          </ul>
          <p>These metrics are designed for aggregation, filtering, and mapping across events.</p>

          <h2>How reports are created?</h2>
          <ol>
            <li>Collect public reporting from multiple sources</li>
            <li>Aggregate details into a consistent schema</li>
            <li>Enrich facts while preserving traceability to sources</li>
            <li>Review for clarity and neutral tone</li>
            <li>Publish a structured, traceable report</li>
            <li>Update if better information appears</li>
          </ol>

            <h2>How this helps?</h2>
          <ul>
            <li>Compare incidents by terrain, season, style, and outcome to surface recurring patterns</li>
            <li>Turn patterns into practical checks during planning and descent timing</li>
            <li>Use shared specifics to align partners and groups on risk decisions</li>
          </ul>

          <h2>How to use this resource?</h2>
          <ul>
            <li>Review similar terrain and season before a trip</li>
            <li>
              In partner or club briefings, ask targeted what-ifs:
              <ul>
                <li>What if timing changed?</li>
                <li>What if a backup or redundancy was added?</li>
                <li>What if earlier communication or location sharing occurred?</li>
              </ul>
            </li>
            <li>Share reports to build common mental models</li>
          </ul>

          <h2>Core principles</h2>
          <ul>
            <li>Clarity over fading memory</li>
            <li>Traceable facts with direct source links</li>
            <li>Structured information for pattern recognition</li>
            <li>Open to explore, reference, and build upon</li>
          </ul>
          <h2>Legal &amp; use notice</h2>
          <p>Information here is compiled from public sources on a best-effort basis and may contain errors or omissions.</p>
          <p>This resource is not a substitute for training, local knowledge, or real-time conditions.</p>
          <p>You are responsible for your decisions and safety.</p>
          <p>The maintainers make no warranties and assume no liability for use of this material.</p>
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
